AGENT_SYSTEM_PROMPT_TEMPLATE = """
你是一个智能旅行助手。你的任务是分析用户的请求，并使用可用工具一步步地解决问题。

# 可用工具:
- `get_weather(city: str)`: 查询指定城市的实时天气。
- `get_attraction(city: str, weather: str)`: 根据城市和天气搜索推荐的旅游景点，每次只能返回一个。
- `check_ticket_status(attraction: str)`: 检查某个景点门票是否售罄（可能返回“售罄/有票”）。

# 核心能力与策略:
## 1) 记忆（用户偏好）
你需要在对话中持续维护一份“用户偏好记忆”，并用于后续推荐的个性化调整。
记忆只记录用户明确表达/确认的信息，避免臆测；如果信息不确定，用提问澄清而不是直接写入记忆。
可记忆的偏好字段包括但不限于：兴趣偏好（历史文化/自然/亲子/美食等）、预算范围、出行日期与同行人、节奏强度、交通方式、限制条件（室内优先/不爬山/少排队等）。
当关键信息缺失会影响推荐质量时，优先用 1-2 个问题澄清。

# 用户偏好
{user_preferences}

# 任务完成:
当你收集到足够的信息，能够回答用户的最终问题时，你必须在`Action:`字段后使用 `finish(answer="...")` 来输出最终答案。

# 票务售罄/不可行时的备选方案
当用户反馈“门票售罄/约不到/闭馆/限流/排队太久”等导致当前推荐不可行时：
1) 再次调用工具获取新的备选景点或替代活动（优先：同类型、同区域、同强度、同预算）
2) 同时给出 1-2 条可执行的替代策略（例如：换时段/换分馆/换同类/选无需预约的替代）
3) 每个备选要说明“为什么适合当备选、如何更容易去/约到”

# 连续拒绝 3 次后的反思与调整
你需要跟踪“连续拒绝计数”（用户明确表示不想去/不喜欢/不要这个推荐，算一次拒绝；仅仅提问不算）。
当连续拒绝达到 3 次时：
- 做一次简短反思：总结被拒绝的共同原因（必须基于用户反馈），并据此调整推荐策略
- 主动提出 1-2 个澄清问题来校准偏好（例如：更想室内还是室外？预算上限？更偏历史还是自然？）
- 下一次推荐要与之前明显不同（更换类型/更换区域/更换强度/加入免费选项等）

# 行动格式（必须严格遵循）:
你的回答必须严格遵循以下格式，并且每次回复只输出一对 Thought-Action：
Thought: 只写“简短计划 + 记忆摘要 + 状态”，不要输出详细推理过程。建议使用以下结构：
  Memory: <用1-3行概括当前已确认的用户偏好；没有则写“暂无已确认偏好”>
  State: <consecutive_rejections=0..3+；如未知可写unknown>
  Plan: <下一步打算做什么：调用工具/向用户澄清/给出推荐>
Action: 这里是你要调用的工具（格式为 function_name(arg_name="arg_value")）；当信息已足够可直接回答时，用 finish(answer="...") 输出最终答案。

请开始吧！
"""


import requests
import json
import random
from pathlib import Path

USER_PREFERENCES_PATH = Path("user_preference.json")


def load_user_preferences() -> dict:
    if not USER_PREFERENCES_PATH.exists():
        return {"喜好": [], "讨厌": [], "预算": ""}
    try:
        with USER_PREFERENCES_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"喜好": [], "讨厌": [], "预算": ""}
        data.setdefault("喜好", [])
        data.setdefault("讨厌", [])
        data.setdefault("预算", "")
        if not isinstance(data["喜好"], list):
            data["喜好"] = []
        if not isinstance(data["讨厌"], list):
            data["讨厌"] = []
        if not isinstance(data["预算"], str):
            data["预算"] = str(data["预算"])
        return data
    except Exception:
        return {"喜好": [], "讨厌": [], "预算": ""}


def save_user_preferences(prefs: dict) -> None:
    with USER_PREFERENCES_PATH.open("w", encoding="utf-8") as f:
        json.dump(prefs, f, ensure_ascii=False, indent=2)


def format_user_preferences_for_prompt(prefs: dict) -> str:
    likes = prefs.get("喜好") or []
    dislikes = prefs.get("讨厌") or []
    budget = prefs.get("预算") or ""
    lines = ["已知用户偏好："]
    lines.append(f"- 喜好：{('、'.join(likes)) if likes else '暂无'}")
    lines.append(f"- 讨厌：{('、'.join(dislikes)) if dislikes else '暂无'}")
    lines.append(f"- 预算：{budget if budget else '暂无'}")
    return "\n".join(lines)


def merge_user_preferences(existing: dict, extracted: dict) -> dict:
    merged = {
        "喜好": list(existing.get("喜好") or []),
        "讨厌": list(existing.get("讨厌") or []),
        "预算": existing.get("预算") or "",
    }
    for key in ("喜好", "讨厌"):
        items = extracted.get(key) or []
        if isinstance(items, list):
            for item in items:
                item = str(item).strip()
                if item and item not in merged[key]:
                    merged[key].append(item)
    budget = extracted.get("预算")
    if isinstance(budget, str) and budget.strip():
        merged["预算"] = budget.strip()
    return merged


def check_ticket_status(attraction: str) -> str:
    """
    随机模拟票务：1/2 概率售罄。
    返回值示例：
    - "售罄"
    - "有票"
    """
    if random.random() < 0.5:
        return "售罄"
    return "有票"

def get_weather(city: str) -> str:
    """
    通过调用 wttr.in API 查询真实的天气信息。
    """
    # API端点，我们请求JSON格式的数据
    url = f"https://wttr.in/{city}?format=j1"
    
    try:
        # 发起网络请求
        response = requests.get(url)
        # 检查响应状态码是否为200 (成功)
        response.raise_for_status() 
        # 解析返回的JSON数据
        data = response.json()
        
        # 提取当前天气状况
        current_condition = data['current_condition'][0]
        weather_desc = current_condition['weatherDesc'][0]['value']
        temp_c = current_condition['temp_C']
        
        # 格式化成自然语言返回
        return f"{city}当前天气：{weather_desc}，气温{temp_c}摄氏度"
        
    except requests.exceptions.RequestException as e:
        # 处理网络错误
        return f"错误：查询天气时遇到网络问题 - {e}"
    except (KeyError, IndexError) as e:
        # 处理数据解析错误
        return f"错误：解析天气数据失败，可能是城市名称无效 - {e}"


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
    "check_ticket_status": check_ticket_status,
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

    def generate(self, messages: list[dict], system_prompt: str) -> str:
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
            messages = [{"role": "system", "content": system_prompt}] + messages
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.7,
                timeout=60.0  # 添加60秒超时
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

PREFERENCE_EXTRACTOR_SYSTEM_PROMPT = """
你是一个“用户旅行偏好抽取器”。你的任务是从对话中抽取用户明确表达或确认的长期偏好，并输出一段严格的 JSON（不要包含任何额外文字、解释或 Markdown）。

抽取规则：
1) 只记录用户明确说过/确认过的内容；不要猜测、不要扩展。
2) 如果信息不够明确，就不要写入。
3) 预算如果出现（如“人均200以内”“不想花太多”），尽量用原话摘要为一个字符串。
4) 输出必须符合下面的 JSON 结构；字段缺失用空数组/空字符串。

输出 JSON 结构（键名必须完全一致）：
{
  "喜好": ["..."],
  "讨厌": ["..."],
  "预算": "..."
}
""".strip()


def extract_user_preferences_from_history(prompt_history: list[dict], llm: OpenAICompatibleClient) -> dict:
    transcript_lines: list[str] = []
    for msg in prompt_history:
        role = msg.get("role", "")
        content = str(msg.get("content", "")).strip()
        if not content:
            continue
        if role == "user":
            transcript_lines.append(f"用户: {content}")
        elif role == "assistant":
            transcript_lines.append(f"助手: {content}")
    transcript = "\n".join(transcript_lines)
    if not transcript:
        return {"喜好": [], "讨厌": [], "预算": ""}

    resp = llm.generate(
        messages=[{"role": "user", "content": transcript}],
        system_prompt=PREFERENCE_EXTRACTOR_SYSTEM_PROMPT,
    )

    def _try_parse_json(text: str) -> dict | None:
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None

    parsed = _try_parse_json(resp)
    if parsed is None:
        m = re.search(r"\{.*\}", resp, re.DOTALL)
        if m:
            parsed = _try_parse_json(m.group(0))
    if parsed is None:
        return {"喜好": [], "讨厌": [], "预算": ""}

    parsed.setdefault("喜好", [])
    parsed.setdefault("讨厌", [])
    parsed.setdefault("预算", "")
    return parsed


def update_user_preferences_from_conversation(conversation_history: list[dict], llm: OpenAICompatibleClient) -> None:
    existing = load_user_preferences()
    extracted = extract_user_preferences_from_history(conversation_history, llm)
    merged = merge_user_preferences(existing, extracted)
    save_user_preferences(merged)

prompt_history = []
def run_agent(user_prompt: str, prompt_history: list[dict], llm: OpenAICompatibleClient) -> dict:
    # --- 3. 运行主循环 ---
    existing_prefs = load_user_preferences()
    system_prompt = AGENT_SYSTEM_PROMPT_TEMPLATE.format(
        user_preferences=format_user_preferences_for_prompt(existing_prefs)
    )
    prompt_history = prompt_history + [{"role": "user", "content": user_prompt}]
    for i in range(10): # 设置最大循环次数
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
        ai_message = []
        print(f"\n=== 第 {i+1} 轮推理 ===")

        # 1. 构建 messages
        messages = prompt_history
        print(f"📊 当前对话历史: {len(messages)} 条消息")

        # 2. 调用 LLM 进行思考
        print("🤔 正在思考...", end='', flush=True)
        try:
            llm_response = llm.generate(messages=messages, system_prompt=system_prompt)
            print(" ✓")  # 成功后打印勾
        except Exception as e:
            print(" ✗")  # 失败后打印叉
            print(f"错误：调用LLM失败 - {str(e)}")
            break

        # 3. 解析并执行行动
        # 提取第一对 Thought-Action（模型可能输出多余的内容，需要截断）
        thought_match = re.search(r'Thought:\s*(.+?)(?=\nAction:)', llm_response, re.DOTALL)
        action_match = re.search(r'Action:\s*(.+?)(?=\n|$)', llm_response, re.DOTALL)

        if not thought_match or not action_match:
            print("错误：LLM输出格式不正确，未找到 Thought 或 Action")
            print("请模型重新思考...")
            ai_message.append(f"LLM输出: {llm_response}")
            ai_message.append("系统提示: 输出格式不正确，请严格按照 Thought-Action 格式输出。")
            prompt_history +=[{"role": "assistant", "content": "\n".join(ai_message)}]
            continue

        thought = thought_match.group(1).strip()
        action = action_match.group(1).strip()

        print(f"Thought: {thought}")
        print(f"Action: {action}")

        # 将本轮的 Thought 和 Action 添加到历史记录
        ai_message.append(f"Thought: {thought}")
        ai_message.append(f"Action: {action}")

        # 检查是否是 finish 动作
        if action.startswith("finish("):
            # 提取 finish 函数的参数
            finish_match = re.search(r'finish\(answer=["\'](.+?)["\']\)', action)
            if finish_match:
                final_answer = finish_match.group(1)
                print(f"\n{'='*40}")
                print(f"最终答案: {final_answer}")
                print(f"{'='*40}")
                prompt_history +=[{"role": "assistant", "content": "\n".join(ai_message)}]
                break
            else:
                print("错误：finish 函数格式不正确")
                ai_message.append("系统提示: finish 函数格式不正确，请使用 finish(answer=\"...\")")
                prompt_history +=[{"role": "assistant", "content": "\n".join(ai_message)}]
                continue

        # 解析并执行工具函数调用
        # 匹配格式：function_name(arg_name="arg_value")
        tool_match = re.search(r'(\w+)\((.+?)\)', action)
        if not tool_match:
            print("错误：Action 格式不正确，无法解析工具调用")
            ai_message.append(f"观察: 工具调用格式错误")
            prompt_history += [{"role": "assistant", "content": "\n".join(ai_message)}]
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
            ai_message.append(f"观察: 参数解析失败 - {str(e)}")
            prompt_history += [{"role": "assistant", "content": "\n".join(ai_message)}]
            continue

        # 4. 执行工具函数并记录观察结果
        if tool_name in available_tools:
            try:
                result = available_tools[tool_name](**tool_kwargs)
                print(f"观察: {result}")
                ai_message.append(f"观察: {result}")
                prompt_history += [{"role": "assistant", "content": "\n".join(ai_message)}]
            except Exception as e:
                error_msg = f"工具执行失败 - {str(e)}"
                print(f"观察: {error_msg}")
                ai_message.append(f"观察: {error_msg}")
                prompt_history += [{"role": "assistant", "content": "\n".join(ai_message)}]
        else:
            error_msg = f"未知工具: {tool_name}，可用工具: {list(available_tools.keys())}"
            print(f"观察: {error_msg}")
            ai_message.append(f"观察: {error_msg}")
            prompt_history += [{"role": "assistant", "content": "\n".join(ai_message)}]

    else:
        # 如果循环正常结束（没有通过 break 退出），说明达到最大循环次数
        print(f"\n{'='*40}")
        print("警告：达到最大循环次数，任务未完成")
        print(f"{'='*40}")
        final_answer = "抱歉，我无法完成这个任务。"

    return {
        "final_answer" : final_answer,
        "prompt_history" : prompt_history
    }

def chat_loop():
    """
    多轮对话主循环
    """
    prompt_history = []
    conversation_history: list[dict] = []
    print("="*50)
    print("欢迎使用智能旅行助手！")
    print("="*50)
    print("我可以帮您：")
    print("  - 查询城市天气")
    print("  - 根据天气推荐旅游景点")
    print("\n输入 'exit', 'quit' 或 '退出' 可以结束对话")
    print("="*50 + "\n")

    while True:
        # 获取用户输入
        try:
            user_input = input("用户: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\n感谢使用，再见！")
            break

        # 检查空输入
        if not user_input:
            print("⚠️  请输入有效的问题\n")
            continue

        # 检查退出指令
        if user_input.lower() in ['exit', 'quit', '退出', '再见', 'bye']:
            print("\n感谢使用，再见！")
            break

        # 执行 Agent 推理
        try:
            result = run_agent(user_input, prompt_history, llm)
            prompt_history = result["prompt_history"]

            # 显示最终答案
            print(f"\n{'='*50}")
            print(f"助手: {result['final_answer']}")
            print(f"{'='*50}\n")

            # 每次对话结束：汇总全量对话历史并更新 user_preference.json
            conversation_history.append({"role": "user", "content": user_input})
            conversation_history.append({"role": "assistant", "content": result["final_answer"]})
            try:
                update_user_preferences_from_conversation(conversation_history, llm)
            except Exception:
                pass

        except Exception as e:
            print(f"\n❌ 执行出错: {str(e)}\n")
            # 错误时不更新历史，让用户可以重试
            continue

if __name__ == "__main__":
    chat_loop()
