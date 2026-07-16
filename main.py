from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_core.messages import HumanMessage
from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END
from typing_extensions import TypedDict
from typing import Dict
import asyncio
import os
import bedrock as bd
import streamlit as st
load_dotenv()
#-local variable––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––-
def load_secrets():
    os.environ["LANGSMITH_API_KEY"] = os.getenv("LANGSMITH_API_KEY")or st.secrets["LANGSMITH_API_KEY"]
    os.environ["OPENAI_API_KEY"] =os.getenv("OPENAI_API_KEY") or st.secrets["OPENAI_API_KEY"]
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_PROJECT"] = "AgentCore"
    os.environ["LANGSMITH_ENDPOINT"] = "https://eu.api.smith.langchain.com"


# ── Tools ─────────────────────────────────────────────────────────────────────
async def get_tools():
    mcp_url= os.getenv("MCP_SERVER_URL") or st.secrets.get("MCP_SERVER_URL","http://127.0.0.1:8000/mcp")
    client = MultiServerMCPClient(
        {"server": {
            "url": "http://127.0.0.1:8000/mcp",
            "transport": "streamable_http"
        }}
    )
    return await client.get_tools()

def bedrock_tools(tools):
    return bd.convert_to_bedrock_tools(tools)

# ── State ─────────────────────────────────────────────────────────────────────
class Orchestrator(TypedDict):
    current_task: str
    messages: list
    langchain_tools:list
    research: str
    fact_check: str
    final_report: str
    next_agent: str
    attempt: int
    task_complete: bool

# ── Agents ────────────────────────────────────────────────────────────────────
async def orch_agent(state: Orchestrator) -> Dict:
    prompt = f"""You are an orchestrator. Based on the state below, return the next agent.
    You will receive a chat history and a current query.
If the query contains pronouns (he, she, they, it), resolve them using the chat history.
Then write a clear, standalone task into current_task before routing to other agents.
Task: {state['current_task']}
- research populated: {bool(state['research'])}
- fact_check populated: {bool(state['fact_check'])}
- final_report populated: {bool(state['final_report'])}
- attempts: {state['attempt']}

Rules (follow in order, stop at first match):
- If research is False -> return collector
- If research is True AND fact_check is False AND task is weather or wikipedia -> return narrator directly, skip verifier
- If research is True AND fact_check is False -> return verifier
- If research is True AND fact_check is True AND final_report is False -> return narrator
- If final_report is True -> return end

Return in this format:
resolved_task:<clean query here>
next_agent:<agent name here>
""" 
    result = await bd.invoke_bedrock(
        system=prompt,
        model_id="us.amazon.nova-2-lite-v1:0",
        message=[{
            "role": "user", 
            "content": [{"text": state["current_task"]}]
        }]
    )
    resolved_task=state["current_task"]
    next_agent="collector"
    for line in result.strip().splitlines():
        if line.startswith("resolved_task:"):
            resolved_task=line.split(":", 1)[1].strip()
        if line.startswith("next_agent:"):
            next_agent =line.split(":",1)[1].strip().lower()
    for keyword in ["collector", "verifier", "narrator", END]:
        if keyword in next_agent:
            next_agent = keyword
            break
    return{"next_agent": next_agent,"current_task":resolved_task}
#data collection agent
async def collector(state: Orchestrator) -> Dict:
    prompt = """You are a research agent. Use the tools to fetch news.
    Instructions:
    - Weather query -> weather tool
    - Older news -> get_old_news with days
    - Sport -> sports_news
    - Specific region -> use region tool
    - Business -> get_business_news
    - Generic/global -> get_global_news
    Return only what you fetch with sources and links.
"""
    langchain_tool = state["langchain_tools"]
    tools = bedrock_tools(langchain_tool)
    result = await bd.invoke_bedrock(
        system=prompt,
        model_id="us.amazon.nova-2-lite-v1:0",
        message=[{
            "role": "user",
            "content": [{"text": state["current_task"]}]
        }],
        tools=tools,
        langchain_tools=langchain_tool,
    )
    return {"research": result, "attempt": state["attempt"] + 1}
#data validation agent
async def validate(state: Orchestrator) -> Dict:
    prompt = f"""You are a validator. Verify the research data below.
    data={state["research"]}
    Instructions:
    - Use the search tool MAXIMUM 2 times only
    - Verify with the search tool
    - Check accuracy and relevance
    - Your output must include ALL data from the research, not just news
    - For weather data, copy it exactly into your validation output
    - Do not summarise or drop weather, Wikipedia, or any non-news content
    - State if validation passed or failed
    Return only the analysis.
"""
    langchain_tool = state["langchain_tools"]
    tools = bedrock_tools(langchain_tool)
    result = await bd.invoke_bedrock(
        system=prompt,
        model_id="us.amazon.nova-2-lite-v1:0",
        message=[{
            "role": "user",
            "content": [{"text": state["current_task"]}]
        }],
        tools=tools,
        langchain_tools=langchain_tool,
    )
    return {"fact_check": result}
#response writer agent
async def narrator(state: Orchestrator) -> Dict:
    prompt =  f"""You are a writer. Turn the data below into a response for the user.
    analysis={state["fact_check"]}
    data={state["research"]}
    original_query={state["current_task"]}

First decide what kind of content and format accordingly:
1.Weather data:
-Present as a table
-Add one short sentence above the tabel(eg:Here is the Weather for )
2.News data:
-Present as a bullet list, one bullet per story
-Each bullet: headline,1-line summary,source name and link if present
-After the list add one line:✅ Verified" if analysis confirms accuracy or
⚠️ Not independently verified" if analysis is empty or flags issues
-Do not fabricate a verification status if analysis is empty — say not verified in that case.
3:Everthing else(wikipedia,summary or general questions,comparison ,explicit report requests):
-Write a Short report with 1-line intro and then 2-4line short section with bold mini-headers if the content has distinct parts
- Otherwise, default to a direct 2-5 sentence conversational answer
-If the research data includes a source link or Wikipedia URL, add it as
  a final line: "Source: <link>"
- If no link is present in the research data, omit this line entirely —
  never invent a URL
Rules:
-Use research as your PRIMARY source of content
-Use analysis only to determine verified/not verified for news, or to
      flag inaccuracies — don't restate it
-Do not include a date unless it came explicitly from the research data
-Never invent data not present in research or analysis
    Return only the final answer, nothing else.

"""
    result = await bd.invoke_bedrock(
        system=prompt,
        model_id="us.amazon.nova-2-lite-v1:0",
        message=[{
            "role": "user",
            "content": [{"text": state["current_task"]}]
        }
        ],
        max_tokens=800,
    )
    return {"final_report": result, "task_complete": True}

# ── Graph ─────────────────────────────────────────────────────────────────────
def graph():
    workflow = StateGraph(Orchestrator)
    workflow.add_node("orch", orch_agent)
    workflow.add_node("collect", collector)
    workflow.add_node("verify", validate)
    workflow.add_node("narrate", narrator)

    workflow.add_edge(START, "orch")
    workflow.add_edge("collect", "orch")
    workflow.add_edge("verify", "orch")
    workflow.add_edge("narrate", END)

    def router(state: Orchestrator):
        return state["next_agent"]

    workflow.add_conditional_edges(
        "orch", router,
        {
            "collector": "collect",
            "verifier": "verify",
            "narrator": "narrate",
            "end": END
        }
    )
    app = workflow.compile()  
    return app

# ── Run ───────────────────────────────────────────────────────────────────────
async def main(query: str,history:list):
    load_secrets()
    langchain_tools=await get_tools()
    app = graph()
    msg_history=""
    if history:
        for msg in history:
            role="User"if msg["role"]=="user" else "Assistant"
            msg_history+=f"{role}:{msg['content']}\n"
    full_query = f"Chat history:\n{msg_history}\nCurrent query: {query}" if msg_history else query
    result = await app.ainvoke({
        "current_task": full_query,
        "messages": [{
            "role": "user",
            "content": [{"text": query}]
        }],
        "langchain_tools": langchain_tools,
        "attempt": 0,
        "task_complete": False,
        "next_agent": "",
        "research": "",      
        "fact_check": "",     
        "final_report": ""    
    })
    return result["final_report"]

