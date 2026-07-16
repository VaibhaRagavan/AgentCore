import streamlit as st
from main import main
import asyncio
import requests
import threading

def wake_server():
    try:
        requests.get("https://agentcore-t1gr.onrender.com/mcp", timeout=5)
    except Exception:
        pass  # ignore errors — this is just a wake-up ping, not a real call

if "server_pinged" not in st.session_state:
    threading.Thread(target=wake_server, daemon=True).start()
    st.session_state["server_pinged"] = True
st.set_page_config(page_title="AgentCore", page_icon="🤖",layout="wide")

WELCOME="Hello 👋 I can help you with Weather, Wikipedia, and News.\n\n💡 For weather, include the country for accuracy e.g. *Dublin, Ireland* or *Mumbai, India*"

#––––session state–––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
if "session_id" not in st.session_state:
    st.session_state.session_id = "chat_1"
if "all_sessions" not in st.session_state:
    st.session_state.all_sessions = {"chat_1": [
        {"role": "assistant", "content": WELCOME}
    ]}
#–––––––sidebar–––––––––––––––––––––––––
with st.sidebar:
    st.header("Chats")
    for s_id in st.session_state.all_sessions:
        if st.button(s_id):
            st.session_state.session_id = s_id
            st.rerun()
    if st.button("+ New Chat"):
        new_session_id =f"chat_{len(st.session_state.all_sessions)+1}"
        st.session_state.all_sessions[new_session_id] = [
            {"role": "assistant", "content": WELCOME}
        ]
        st.session_state.session_id = new_session_id
        st.rerun()

message=st.session_state.all_sessions[st.session_state.session_id]
#–––Chat–––––––––––––––––––––––––––––––––––––––––
for msg in message:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
query=st.chat_input("Write a message...")
history=message[-5:]
if query:
    message.append({"role": "user", "content": query})
    with st.chat_message("user"):
        st.markdown(query)
    with st.chat_message("assistant"):
        #––––waking up the mcp server–––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
        with st.spinner("Waking up the assistant and processing your query... request may take up to a minute""):
            result = asyncio.run(main(query,history))
            st.markdown(result)
    message.append({"role": "assistant", "content": result})
