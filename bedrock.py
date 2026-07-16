import boto3
import asyncio,json

bedrock=boto3.client("bedrock-runtime", region_name="us-east-1")
##bedrock invocation for async flow
async def invoke_bedrock(
        model_id:str,
        system:str,
        message:list,
        tools:list=None,
        langchain_tools: list = None,
        max_tokens:int=1500):
    #bedrock body 
    body={
        "modelId":model_id,
        "inferenceConfig":{
            "maxTokens":max_tokens},
        "messages":message,
        "system":[
            {"text":system}
        ],
    }

    if tools:
        body["toolConfig"]={"tools": tools}
    while True:
        #invoke bedrock
        loop=asyncio.get_event_loop()
        response=await loop.run_in_executor(
            None,
        lambda:bedrock.converse(**body)
    )
        content=response["output"]["message"]["content"]
        stopReason=response["stopReason"]
        #model finished ,retun the text
        if stopReason=="end_turn":
            text_blocks=[]
            for block in content:
                if "text" in block:
                    text_blocks.append(block["text"])
            return text_blocks[0] if text_blocks else ""
        elif stopReason =="tool_use":
           #append the assistant msg with tool call
            body["messages"].append({
                "role":"assistant",
                "content":content
            })
            #find and execute the toll call
            tool_result=[]
            for block in content:
                if "toolUse" not in block:
                    continue
                tool_name   = block["toolUse"]["name"]
                tool_input  = block["toolUse"]["input"]
                tool_use_id = block["toolUse"]["toolUseId"]
                print(f"calling {tool_name} with {tool_input}")
                # find matching langchain tool and call it
                result_text=f"Tool {tool_name} not found"
                if langchain_tools:
                    for tool in langchain_tools:
                        if tool.name==tool_name:
                            try:
                                result_text=await tool.ainvoke(tool_input)
                            except Exception as e:
                                result_text=f"Tool{tool_name} failes {str(e)}"
                            break
                print(f"result: {str(result_text)[:500]}")
                tool_result.append({
                    "toolResult":{
                        "toolUseId":tool_use_id,
                        "content":[{"text":str(result_text)}]
                    }
                })
            body["messages"].append({
            "role":"user",
            "content":tool_result
            })
        else:
            raise ValueError(f"Unknown stop reason: {stopReason}")
            break

    return ""
##Tools for the bedrock function

def convert_to_bedrock_tools(tools:list)->list:
    "Convert mcp tools to bedrock tools"
    bedrock_tools=[]
    for tool in tools:
        bedrock_tools.append({
            "toolSpec":{
                "name":tool.name,
            "description":tool.description,
            "inputSchema":{
                "json":{
                    "type":tool.args_schema["type"],
                    "properties":tool.args_schema["properties"],
                    "required":tool.args_schema["required"],
                    
                }
            }

            }
            
        })
    return bedrock_tools
 