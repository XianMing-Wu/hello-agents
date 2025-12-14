AGENT_SYSTEM_PROMPT = """
你是一个智能旅行助手。你的任务是分析用户的请求，并使用可用工具一步步地解决问题。

# 可用工具:
- `get_weather(city: str)`: 查询指定城市的实时天气。
- `get_attraction(city: str, weather: str)`: 根据城市和天气搜索推荐的旅游景点。

# 行动格式:
你的回答必须严格遵循以下格式。首先是你的思考过程，然后是你要执行的具体行动，每次回复只输出一对Thought-Action：
Thought: [这里是你的思考过程和下一步计划]
Action: [这里是你要调用的工具，格式为 function_name(arg_name="arg_value")]

# 任务完成:
当你收集到足够的信息，能够回答用户的最终问题时，你必须在`Action:`字段后使用 `finish(answer="...")` 来输出最终答案。

请开始吧！
"""


import requests
import json

def get_weather(city: str) -> str:
    """
    通过调用 wttr.in API 查询真实的天气信息。
    Args:
        city (str): 要查询的城市名称。
    return:
        str: 天气信息，格式为 "城市名称 当前天气：xxxxxx，气温xxxxxx"。

    示例:
    >>> get_weather("北京")
    "北京当前天气：多云，气温25.0摄氏度"
    说明：
    1. 向https://wttr.in/{city}?format=j1端点请求数据
    2. 需要处理错误，比如API返回了错误码或者没有返回数据。
    """
    try:
        # 向 wttr.in API 发送请求，获取 JSON 格式的天气数据
        url = f"https://wttr.in/{city}?format=j1"
        response = requests.get(url, timeout=10)

        # 检查响应状态码
        if response.status_code != 200:
            return f"无法获取{city}的天气信息，API返回错误码: {response.status_code}"

        # 解析JSON数据
        data = response.json()

        # 检查数据完整性
        if not data or 'current_condition' not in data or not data['current_condition']:
            return f"无法获取{city}的天气信息，API返回数据不完整"

        # 提取当前天气信息
        current = data['current_condition'][0]
        weather_desc = current.get('lang_zh', [{}])[0].get('value', current.get('weatherDesc', [{}])[0].get('value', '未知'))
        temp_c = current.get('temp_C', '未知')

        return f"{city}当前天气：{weather_desc}，气温{temp_c}摄氏度"

    except requests.exceptions.Timeout:
        return f"获取{city}天气信息超时，请稍后重试"
    except requests.exceptions.RequestException as e:
        return f"获取{city}天气信息失败：网络错误 - {str(e)}"
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        return f"获取{city}天气信息失败：数据解析错误 - {str(e)}"
    except Exception as e:
        return f"获取{city}天气信息时发生未知错误：{str(e)}"


import os
from tavily import TavilyClient

def get_attraction(city: str, weather: str) -> str:
    """
    根据城市和天气，使用Tavily Search API搜索并返回优化后的景点推荐。
    Args:
        city (str): 要查询的城市名称。
        weather (str): 天气信息，格式为 "xxxxxx，气温xxxxxx"。
    Returns:
        str: ai搜索返回的结果。

    示例:
    >>> get_attraction("北京", "多云，气温25.0摄氏度")
    "北京最值得去的景点推荐及理由：\n- 1. 故宫：故宫是北京最大的历史建筑，也是中国最 iconic的博物馆。\n- 2. 颐和园：颐和园是北京最大的历史建筑，也是中国最 iconic的博物馆。\n- 3. 景山：景山是北京最大的历史建筑，也是中国最 iconic的博物馆。\n- 4. 景泰路：景泰路是北京最大的历史建筑，也是中国最 iconic的博物馆。"
    说明：
    1. 使用Tavily Search API搜索并返回优化后的景点推荐。
    2. 需要处理错误，比如API返回了错误码或者没有返回数据。
    3. 需要仔细阅读API文档，确保正确获取搜索返回的结果
    """
    try:
        # 获取环境变量中的 Tavily API Key
        api_key = os.getenv("TAVILY_API_KEY")
        if not api_key:
            return "错误：未设置 TAVILY_API_KEY 环境变量"

        # 初始化 Tavily 客户端
        tavily_client = TavilyClient(api_key=api_key)

        # 构建搜索查询，结合城市和天气信息
        query = f"{city}适合{weather}去的旅游景点推荐"

        # 执行搜索，使用 include_answer=True 来获取 AI 生成的答案
        response = tavily_client.search(
            query=query,
            search_depth="basic",
            max_results=5,
            include_answer=True
        )

        # 检查返回结果
        if not response:
            return f"无法获取{city}的景点推荐，Tavily API 返回空结果"

        # 优先返回 AI 生成的答案
        if 'answer' in response and response['answer']:
            return response['answer']

        # 如果没有答案，则从搜索结果中构建回复
        if 'results' in response and response['results']:
            result_text = f"{city}景点推荐：\n"
            for i, result in enumerate(response['results'][:3], 1):
                title = result.get('title', '未知景点')
                content = result.get('content', '暂无描述')
                # 截取内容的前150个字符
                content_snippet = content[:150] + "..." if len(content) > 150 else content
                result_text += f"{i}. {title}\n   {content_snippet}\n\n"
            return result_text.strip()

        return f"无法获取{city}的景点推荐，未找到相关信息"

    except Exception as e:
        return f"获取{city}景点推荐时发生错误：{str(e)}"


# 将所有工具函数放入一个字典，方便后续调用
available_tools = {
    "get_weather": get_weather,
    "get_attraction": get_attraction,
}

from openai import OpenAI

class OpenAICompatibleClient:
    """
    一个用于调用任何兼容OpenAI接口的LLM服务的客户端。
    1. __init__(self, model: str, api_key: str, base_url: str):
    2. generate(self, prompt: str, system_prompt: str) -> str:
    说明：
    1. 需要调用openai库
    """

    def __init__(self, model: str, api_key: str, base_url: str):
        """
        初始化 OpenAI 兼容客户端。
        Args:
            model (str): 要使用的模型ID。
            api_key (str): API密钥。
            base_url (str): API的基础URL。
        """
        self.model = model
        self.client = OpenAI(api_key=api_key, base_url=base_url)

    def generate(self, prompt: str, system_prompt: str) -> str:
        """
        生成聊天完成响应。
        Args:
            prompt (str): 用户提示信息。
            system_prompt (str): 系统提示信息。
        Returns:
            str: 模型生成的响应内容。
        """
        try:
            # 调用 OpenAI 的 chat completions API
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7
            )

            # 提取并返回助手的回复
            if response.choices and len(response.choices) > 0:
                return response.choices[0].message.content
            else:
                return "错误：模型未返回有效响应"

        except Exception as e:
            return f"生成响应时发生错误：{str(e)}"

import re

# --- 1. 配置LLM客户端 ---
# 请根据您使用的服务，将这里替换成对应的凭证和地址
from dotenv import load_dotenv
load_dotenv()
API_KEY = os.getenv("OPENAI_API_KEY")
BASE_URL = os.getenv("OPENAI_BASE_URL")
MODEL_ID = "deepseek-chat"
os.environ['TAVILY_API_KEY'] = os.getenv("TAVILY_API_KEY")

llm = OpenAICompatibleClient(
    model=MODEL_ID,
    api_key=API_KEY,
    base_url=BASE_URL
)

# --- 2. 初始化 ---
user_prompt = "你好，请帮我查询一下今天北京的天气，然后根据天气推荐一个合适的旅游景点。"
prompt_history = [f"用户请求: {user_prompt}"]

print(f"用户输入: {user_prompt}\n" + "="*40)

# --- 3. 运行主循环 ---
for i in range(5): # 设置最大循环次数
    """
    1. 构建Prompt
    2. 调用LLM进行思考
    3. 解析并执行行动
    4. 记录观察结果

    说明：
    1. 模型可能会输出多余的Thought-Action，需要截断
    2. 任务完成时，模型会输出 "finish(answer='最终答案')"，此时循环结束
    3. 需要具备错误处理能力，比如模型输出了错误信息或者没有返回结果

    """
    print(f"\n=== 第 {i+1} 轮推理 ===")

    # 1. 构建 Prompt - 将历史记录整合成一个完整的 prompt
    full_prompt = "\n".join(prompt_history)

    # 2. 调用 LLM 进行思考
    try:
        llm_response = llm.generate(prompt=full_prompt, system_prompt=AGENT_SYSTEM_PROMPT)
        # print(f"LLM输出:\n{llm_response}\n")  # 调试用，可选显示原始输出
    except Exception as e:
        print(f"错误：调用LLM失败 - {str(e)}")
        break

    # 3. 解析并执行行动
    # 提取第一对 Thought-Action（模型可能输出多余的内容，需要截断）
    thought_match = re.search(r'Thought:\s*(.+?)(?=\nAction:)', llm_response, re.DOTALL)
    action_match = re.search(r'Action:\s*(.+?)(?=\n|$)', llm_response, re.DOTALL)

    if not thought_match or not action_match:
        print("错误：LLM输出格式不正确，未找到 Thought 或 Action")
        print("请模型重新思考...")
        prompt_history.append(f"LLM输出: {llm_response}")
        prompt_history.append("系统提示: 输出格式不正确，请严格按照 Thought-Action 格式输出。")
        continue

    thought = thought_match.group(1).strip()
    action = action_match.group(1).strip()

    print(f"Thought: {thought}")
    print(f"Action: {action}")

    # 将本轮的 Thought 和 Action 添加到历史记录
    prompt_history.append(f"Thought: {thought}")
    prompt_history.append(f"Action: {action}")

    # 检查是否是 finish 动作
    if action.startswith("finish("):
        # 提取 finish 函数的参数
        finish_match = re.search(r'finish\(answer=["\'](.+?)["\']\)', action)
        if finish_match:
            final_answer = finish_match.group(1)
            print(f"\n{'='*40}")
            print(f"任务完成！")
            print(f"最终答案: {final_answer}")
            print(f"{'='*40}")
            break
        else:
            print("错误：finish 函数格式不正确")
            prompt_history.append("系统提示: finish 函数格式不正确，请使用 finish(answer=\"...\")")
            continue

    # 解析并执行工具函数调用
    # 匹配格式：function_name(arg_name="arg_value")
    tool_match = re.search(r'(\w+)\((.+?)\)', action)
    if not tool_match:
        print("错误：Action 格式不正确，无法解析工具调用")
        prompt_history.append(f"观察: 工具调用格式错误")
        continue

    tool_name = tool_match.group(1)
    tool_args_str = tool_match.group(2)

    # 解析参数
    try:
        # 提取所有参数，格式为 arg_name="arg_value"
        args_matches = re.findall(r'(\w+)=["\'](.+?)["\']', tool_args_str)
        tool_kwargs = {key: value for key, value in args_matches}
    except Exception as e:
        print(f"错误：解析工具参数失败 - {str(e)}")
        prompt_history.append(f"观察: 参数解析失败 - {str(e)}")
        continue

    # 4. 执行工具函数并记录观察结果
    if tool_name in available_tools:
        try:
            result = available_tools[tool_name](**tool_kwargs)
            print(f"观察: {result}")
            prompt_history.append(f"观察: {result}")
        except Exception as e:
            error_msg = f"工具执行失败 - {str(e)}"
            print(f"观察: {error_msg}")
            prompt_history.append(f"观察: {error_msg}")
    else:
        error_msg = f"未知工具: {tool_name}，可用工具: {list(available_tools.keys())}"
        print(f"观察: {error_msg}")
        prompt_history.append(f"观察: {error_msg}")

else:
    # 如果循环正常结束（没有通过 break 退出），说明达到最大循环次数
    print(f"\n{'='*40}")
    print("警告：达到最大循环次数，任务未完成")
    print(f"{'='*40}")
