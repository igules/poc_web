import streamlit as st
import json
import os
from typing import List
from pathlib import Path
from openai import OpenAI

st.set_page_config(page_title="금융고민 상담소", page_icon="💸", layout="centered")
FILE_NAME = "reasoning.txt"

def init_state() -> None:
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "pending_options" not in st.session_state:
        st.session_state.pending_options = []
    if "option_set_id" not in st.session_state:
        st.session_state.option_set_id = 0


def fallback_three_responses(user_input: str) -> List[str]:
    """실패 시 선택지 대신 재입력 안내 메시지를 남기고 옵션은 비운다."""
    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": "응답 생성에 실패했어요. 내용을 다시 입력해줘.",
        }
    )
    return []


def parse_answers(raw_text: str) -> List[str]:
    """모델 응답에서 answers를 추출한다(1개 또는 3개 허용)."""
    cleaned_text = raw_text.strip()
    if cleaned_text.startswith("```"):
        cleaned_text = cleaned_text.strip("`")
        if cleaned_text.startswith("json"):
            cleaned_text = cleaned_text[4:].strip()

    try:
        payload = json.loads(cleaned_text)
        answers = payload.get("answers", [])
        
        reasoning = payload.get("reasoning", [])
        with open(FILE_NAME, "a", encoding="utf-8") as f:
            f.write("REASONING: " + str(reasoning) + "\n")

        if isinstance(answers, str):
            one = answers.strip()
            return [one] if one else []
        if isinstance(answers, list):
            cleaned = [str(x).strip() for x in answers if str(x).strip()]
            if cleaned:
                return cleaned
    except Exception:
        pass

    lines = [line.strip("-* 0123456789.").strip() for line in raw_text.splitlines()]
    return [line for line in lines if line]


def load_api_key() -> str:
    """openai_api_key.txt에서만 API 키를 읽는다."""
    txt_file = Path(__file__).resolve().parent / "openai_api_key.txt"
    if not txt_file.exists():
        return ""

    try:
        with txt_file.open("r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""

def load_prompt_text() -> str:
    prompt_file = Path(__file__).resolve().parent / "prompt.txt"
    if not prompt_file.exists():
        return ""
    try:
        return prompt_file.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def generate_three_responses(user_input: str, history: List[dict] = None) -> List[str]:
    """OpenAI API로 사용자 입력에 대한 3개 답변 후보를 생성한다."""
    api_key = load_api_key()

    if not api_key:
        st.warning("API 키를 찾지 못했습니다. openai_api_key.txt 경로를 확인하세요.")
        return fallback_three_responses(user_input)

    if history is None:
        history = []
    
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        prompt = load_prompt_text()

        if not prompt:
            st.error("prompt.txt를 찾을 수 없거나 비어 있습니다.")
            return fallback_three_responses(user_input)
        messages = [
                {
                "role": "developer",
                "content": [
                    {
                    "type": "text",
                    "text": "너는 사용자의 금융 고민을 듣고 조언을 해주는 어시스턴트야. 사용자는 주로 새롭게 생긴 여유자금에 대한 고민을 상담할거야. 그 고민에 대해서 최종 조언을 주는게 목표야. \n"
                    }
                ]
                },
                {
                "role": "user",
                "content": [
                    {
                    "type": "text",
                    "text": f"{prompt}"
                    }
                ]
                }
            ]
        messages.extend(history)

        response = client.chat.completions.create(
            model = "gpt-5.1",
            messages = messages,
            response_format={"type": "text"},
            verbosity="medium",
            reasoning_effort="medium",
            store=False
        )

        content = response.choices[0].message.content
        print(type(content))
        print(content)

        answers = parse_answers(content)
        if len(answers) == 1:
            st.session_state.messages.append({"role": "assistant", "content": answers[0]})
            return []
        if len(answers) >= 3:
            return answers[:3]
    except Exception as e:
        print("error 발생")
        print(e)
        pass

    st.error("OpenAI API 호출에 실패해 기본 응답으로 전환합니다.")
    return fallback_three_responses(user_input)



def escape_markdown_tilde(text: str) -> str:
    return text.replace("~", "\\~")

def select_option(index: int) -> None:
    selected = st.session_state.pending_options[index]
    st.session_state.messages.append({"role": "assistant", "content": selected})
    st.session_state.pending_options = []
    st.session_state.option_set_id += 1

def reset_chat() -> None:
    st.session_state.messages = []
    st.session_state.pending_options = []
    st.session_state.option_set_id += 1

init_state()

st.title("💸 금융고민 상담소")

st.caption("""
당신은 최근 여유자금으로 300만원이 생겼습니다.
이 여유자금을 불리고자 해당 어시스턴트에 조언을 구하는 상황을 가정합니다.
어시스턴트에 금융 조언을 구하는 질문으로 대화를 시작해주세요.
""")

for msg in st.session_state.messages:
    avatar = "🙂" if msg["role"] == "user" else "👾"
    with st.chat_message(msg["role"], avatar=avatar):
        st.markdown(escape_markdown_tilde(msg["content"]))

if st.session_state.pending_options:
    st.markdown("3개의 질문 중 선호하는 질문 하나를 선택하여 답변해주세요🧐")
    for i, option in enumerate(st.session_state.pending_options):
        key = f"opt_{st.session_state.option_set_id}_{i}"
        safe_option = escape_markdown_tilde(option)
        if st.button(f"{i + 1}. {safe_option}", key=key, use_container_width=True):
            select_option(i)
            st.rerun()

user_prompt = st.chat_input(
    "메시지를 입력하세요",
    disabled = bool(st.session_state.pending_options),
)

if user_prompt:
    st.session_state.messages.append({"role": "user", "content": user_prompt})
    with st.spinner("로딩중..."):
        st.session_state.pending_options = generate_three_responses(user_prompt, history=list(st.session_state.get("messages", []))[-10:])
    st.rerun()
