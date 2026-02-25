import streamlit as st
import json
import os
import html
import pandas as pd
from typing import List
from pathlib import Path
from openai import OpenAI

import time
from supabase import create_client


st.set_page_config(page_title="금융고민 상담소", page_icon="💸", layout="wide")
FILE_NAME = "reasoning.txt"
TURN_LOG_JSONL = "turn_logs.jsonl"
TURN_LOG_XLSX = "turn_logs.xlsx"

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def save_log(json_log):
    try:
        # data = {
        #     "user_name": json_log["user_name"],
        #     "session": json_log['session'],
        #     "user": json_log['user'],
        #     "assistant": json_log['assistant'],
        #     "assistant_selected": json_log['assistant_selected'],
        #     "bad_idx":json_log['bad_idx'],
        #     "good_idx":json_log['good_idx'],
        #     "bad_reason":json_log['bad_reason'],
        #     "good_reason":json_log['good_reason'],
        #     "reasoning":json_log['reasoning']
        # }
        # print(data)
        # st.write(data)

        response = supabase.table("conv_log").insert(json_log).execute()
        # st.write(response)

        if response.data:
            return True
        else:
            st.error("저장 실패")
            return False

    except Exception as e:
        
        st.error(f"에러 발생: {e}")
        return False

def init_state() -> None:
   if "messages" not in st.session_state:
       st.session_state.messages = []
   if "pending_options" not in st.session_state:
       st.session_state.pending_options = []
   if "option_set_id" not in st.session_state:
       st.session_state.option_set_id = 0
   if "session_id" not in st.session_state:
       st.session_state.session_id = 1
   if "feedback" not in st.session_state:
       st.session_state.feedback = {}
   if "option_feedback" not in st.session_state:
       st.session_state.option_feedback = {}
   if "turn_logs" not in st.session_state:
       st.session_state.turn_logs = []
   if "pending_turn" not in st.session_state:
       st.session_state.pending_turn = None
   if "export_done" not in st.session_state:
       st.session_state.export_done = False
   if "export_path" not in st.session_state:
       st.session_state.export_path = ""
   if "last_reasoning" not in st.session_state:
       st.session_state.last_reasoning = ""
   if "user_name" not in st.session_state:
       st.session_state.user_name = ""
   if "experiment_started" not in st.session_state:
       st.session_state.experiment_started = False


def append_turn_log(record: dict) -> None:
    record_with_name = dict(record)
    record_with_name["user_name"] = st.session_state.get("user_name", "")
    st.session_state.turn_logs.append(record_with_name)
    
    with open(TURN_LOG_JSONL, "a", encoding="utf-8") as f:
        f.write(json.dumps(record_with_name, ensure_ascii=False) + "\n")


def export_turn_logs_to_excel() -> str:
    jsonl_path = Path(__file__).resolve().parent / TURN_LOG_JSONL
    if not jsonl_path.exists() or jsonl_path.stat().st_size == 0:
        return ""

    try:
        df = pd.read_json(jsonl_path, lines=True)
    except ValueError as e:
        print(e)
        return ""

    if df.empty:
        return ""

    if "assistant" in df.columns:
        df["assistant"] = df["assistant"].apply(
            lambda x: "\n\n".join(x) if isinstance(x, list) else str(x)
        )

    output_path = str(Path(__file__).resolve().parent / TURN_LOG_XLSX)
    df.to_excel(output_path, index=False)

    return output_path

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
      
       reasoning = payload.get("reasoning", "")
       st.session_state.last_reasoning = str(reasoning)
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
   """환경변수 OPENAI_API_KEY에서만 API 키를 읽는다."""
   return os.getenv("OPENAI_API_KEY", "").strip()


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
       st.warning("API 키를 찾지 못했습니다. 환경변수 OPENAI_API_KEY를 설정해주세요.")
       return fallback_three_responses(user_input)


   if history is None:
       history = []
  
   try:
       from openai import OpenAI

       client = OpenAI(
           api_key=api_key
       )
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
                   "text": "너는 사용자의 금융 고민을 듣고 조언을 해주는 어시스턴트야. 그 고민에 대해서 최종 조언을 주는게 목표야. \n"
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
           model = "gpt-5.2",
           messages = messages,
           response_format={"type": "text"},
           reasoning_effort="medium",
           verbosity="medium",
           store=False
       )
    
       content = response.choices[0].message.content
       print(type(content))
       print(content)


       answers = parse_answers(content)


       ## Save assistant's answers
    #    with open('history.txt', 'a') as f:
    #        f.write("[ASSISTANT]\n" + "\n".join(answers) + "\n")


       if len(answers) == 1:
           st.session_state.messages.append({"role": "assistant", "content": answers[0]})
           single_payload = {
               "user_name": st.session_state.get("user_name", ""),
               "session": st.session_state.session_id,
               "user": user_input,
               "assistant": [answers[0]],
               "assistant_selected": answers[0],
               "bad_idx": None,
               "good_idx": None,
               "bad_reason": "",
               "good_reason": "",
               "reasoning": st.session_state.get("last_reasoning", ""),
           }
           save_log(single_payload)
           st.session_state.pending_turn = None
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


def format_for_markdown(text: str) -> str:
   """줄바꿈을 화면에 그대로 보이도록 Markdown 형식으로 변환한다."""
   return escape_markdown_tilde(text).replace("\n", "  \n")


def format_for_html(text: str) -> str:
   """HTML 카드 내부에서 줄바꿈이 보이도록 변환한다."""
   return html.escape(text).replace("\n", "<br>")


def select_option(index: int) -> None:
    current_set = st.session_state.option_set_id
    feedback = st.session_state.option_feedback.get(current_set, {})
    good_idx = feedback.get("good")
    bad_idx = feedback.get("bad")

    if good_idx is None or bad_idx is None:
        st.warning("진행하려면 3개 답변 중 good 1개와 bad 1개를 먼저 선택해주세요.")
        return

    selected = st.session_state.pending_options[index]

    st.session_state.messages.append({"role": "assistant", "content": selected})

    pending_turn = st.session_state.pending_turn or {}
    
    save_log(
        {
           "user_name": st.session_state.get("user_name", ""),
           "session": pending_turn.get("session", st.session_state.session_id),
           "user": pending_turn.get("user", ""),
           "assistant": pending_turn.get("assistant", list(st.session_state.pending_options)),
           "assistant_selected": selected,
           "bad_idx": bad_idx,
           "good_idx": good_idx,
           "bad_reason": feedback.get("bad_reason", ""),
           "good_reason": feedback.get("good_reason", ""),
           "reasoning": pending_turn.get("reasoning", st.session_state.get("last_reasoning", "")),
       }
    )
    
    st.session_state.pending_options = []
    st.session_state.option_feedback.pop(current_set, None)
    st.session_state.pending_turn = None
    st.session_state.option_set_id += 1


def reset_chat() -> None:
   st.session_state.messages = []
   st.session_state.pending_options = []
   st.session_state.feedback = {}
   st.session_state.option_feedback = {}
   st.session_state.pending_turn = None
   st.session_state.option_set_id += 1


init_state()
st.title("💸 사용자 실험")

if not st.session_state.experiment_started:
   left, center, right = st.columns([2, 3, 2])
   with center:
       st.markdown("### 실험 시작 전 정보를 입력해주세요😃")
       name_value = st.text_input(
           "이름",
           value=st.session_state.user_name,
           placeholder="이름을 입력하세요",
       )
       if st.button("실험 시작", type="primary", use_container_width=True):
           clean_name = name_value.strip()
           if not clean_name:
               st.warning("이름을 입력해주세요.")
           else:
               st.session_state.user_name = clean_name
               st.session_state.session_id = 1
               st.session_state.experiment_started = True
               st.rerun()
   st.stop()

if st.session_state.session_id == 3:
   st.markdown(
       """
       ### 🎉 실험이 종료되었습니다


       참여해주셔서 감사합니다 🙏 
       창을 닫아주세요.
       """
   )
   if st.session_state.export_path:
       st.success(f"결과 파일 저장 완료: {st.session_state.export_path}")
   st.stop()


col1, col2 = st.columns([9, 1])

with col1:
   if st.session_state.session_id == 1:
       st.markdown(f"""
           ### __[🧪 Session #{st.session_state.session_id}]__
           당신은 최근 여유자금으로 2000만원이 생겼습니다.
           이 여유자금을 불리고자 해당 어시스턴트에 조언을 구하는 상황을 가정합니다.
           어시스턴트에 금융 조언을 구하는 질문으로 대화를 시작해주세요.
           """)
   else :
       st.markdown(f"""
           ### __[🧪 Session #{st.session_state.session_id}]__
           투자와 관련된 개인적인 고민으로 어시스턴트와 대화를 시작해주세요 (예. 
노후를 위해 보통 얼마를 모아야 하는지 언제부터 준비를 시작해야할지 고민이다, 신용카드랑 체크카드 비중을 어떻게해야 연말정산에 유리한지 궁금해)
           """)


with col2:
    if st.session_state.session_id == 1:
       label = "✨ 다음 세션"
    elif st.session_state.session_id == 2:
       label = "✨ 실험 종료"


    if st.button(label, type="primary"):
        st.session_state.session_id += 1
        st.session_state.messages = []
        st.session_state.pending_options = []
        st.session_state.feedback = {}
        st.session_state.option_feedback = {}
        st.session_state.pending_turn = None
        st.session_state.option_set_id += 1
          
        st.rerun()

st.divider()

for idx, msg in enumerate(st.session_state.messages):
   avatar = "🙂" if msg["role"] == "user" else "👾"
   with st.chat_message(msg["role"], avatar=avatar):
       st.markdown(format_for_markdown(msg["content"]))


if st.session_state.pending_options:
   st.markdown("3개의 질문 중 선호하는 질문 하나를 선택하여 답변해주세요🧐")
   st.markdown(
       """
       <style>
       .option-card {
           padding: 12px;
           height: 220px;
           background: #ffffff;
           overflow-y: auto;
       }
       </style>
       """,
       unsafe_allow_html=True,
   )


   options = st.session_state.pending_options
   current_set = st.session_state.option_set_id

   if current_set not in st.session_state.option_feedback:
       st.session_state.option_feedback[current_set] = {
           "good": None,
           "bad": None,
           "good_reason": "",
           "bad_reason": "",
       }
   option_fb = st.session_state.option_feedback[current_set]

   cols = st.columns(len(options))  # 👈 가로 컬럼 생성


   for i, option in enumerate(options):
       key_prefix = f"{st.session_state.option_set_id}_{i}"


       with cols[i]:
           safe_option = format_for_html(option)
           st.markdown(
               f'<div class="option-card"><strong>{i + 1}.</strong> {safe_option}</div>',
               unsafe_allow_html=True,
           )

           st.markdown(
               f"""
               <style>
               .st-key-mark_good_{key_prefix} button {{
                   border: 2px solid #86efac !important;
               }}
               .st-key-mark_bad_{key_prefix} button {{
                   border: 2px solid #fca5a5 !important;
               }}
               </style>
               """,
               unsafe_allow_html=True,
           )

           mark_col1, mark_col2 = st.columns(2)
           with mark_col1:
               is_good = option_fb.get("good") == i
               good_label = "✅ good" if is_good else "👍 good"
               if st.button(good_label, key=f"mark_good_{key_prefix}", use_container_width=True):
                   option_fb["good"] = i
                   if option_fb.get("bad") == i:
                       option_fb["bad"] = None
                #    with open("history.txt", "a", encoding="utf-8") as f:
                #        f.write(f"[OPTION_MARK] set={current_set} option={i} mark=good\n")
                   st.rerun()
           with mark_col2:
               is_bad = option_fb.get("bad") == i
               bad_label = "✅ bad" if is_bad else "👎 bad"
               if st.button(bad_label, key=f"mark_bad_{key_prefix}", use_container_width=True):
                   option_fb["bad"] = i
                   if option_fb.get("good") == i:
                       option_fb["good"] = None
                #    with open("history.txt", "a", encoding="utf-8") as f:
                #        f.write(f"[OPTION_MARK] set={current_set} option={i} mark=bad\n")
                   st.rerun()

   if option_fb.get("good") is not None:
       good_reason_key = f"good_reason_{current_set}"
       if good_reason_key not in st.session_state:
           st.session_state[good_reason_key] = option_fb.get("good_reason", "")
       st.text_area(
           "good로 선택한 이유",
           key=good_reason_key,
           placeholder="왜 이 답변이 가장 좋았는지 적어주세요.",
       )
       option_fb["good_reason"] = st.session_state.get(good_reason_key, "").strip()

   if option_fb.get("bad") is not None:
       bad_reason_key = f"bad_reason_{current_set}"
       if bad_reason_key not in st.session_state:
           st.session_state[bad_reason_key] = option_fb.get("bad_reason", "")
       st.text_area(
           "bad로 선택한 이유",
           key=bad_reason_key,
           placeholder="왜 이 답변이 아쉬웠는지 적어주세요.",
       )
       option_fb["bad_reason"] = st.session_state.get(bad_reason_key, "").strip()

   if option_fb.get("good") is None or option_fb.get("bad") is None:
       st.info("다음으로 진행하려면 good 1개와 bad 1개를 각각 선택해주세요.")
   else:
       st.success("good 1개 / bad 1개 선택 완료")

   st.markdown(
       """
       <style>
       .next-action-wrap {
           margin-top: 10px;
           padding: 14px;
           background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
       }
       .next-action-title {
           font-size: 0.92rem;
           font-weight: 700;
           color: #0f172a;
           margin-bottom: 8px;
       }
       </style>
       <div class="next-action-wrap">
         <div class="next-action-title">다음 대화에 사용할 답변을 선택하고 진행하세요</div>
       </div>
       """,
       unsafe_allow_html=True,
   )

   col_select, col_next = st.columns([7, 2])
   with col_select:
       selected_idx = st.selectbox(
           "대화를 이어갈 답변 선택",
           options=list(range(len(options))),
           format_func=lambda x: f"{x + 1}번 답변 사용",
           key=f"next_choice_{current_set}",
           label_visibility="collapsed",
       )
   with col_next:
       if st.button(
           "➡ 다음으로 진행",
           type="primary",
           disabled=option_fb.get("good") is None or option_fb.get("bad") is None,
           use_container_width=True,
       ):
           
           select_option(selected_idx)
           st.rerun()


user_prompt = st.chat_input(
   "메시지를 입력하세요",
   disabled = bool(st.session_state.pending_options),
)


# if user_prompt and not st.session_state.pending_options:
if user_prompt:
   st.session_state.messages.append({"role": "user", "content": user_prompt})
   st.session_state.pending_turn = {
       "session": st.session_state.session_id,
       "user": user_prompt,
       "assistant": [],
       "reasoning": "",
   }
   with st.spinner("로딩중..."):
       st.session_state.pending_options = generate_three_responses(user_prompt, history=list(st.session_state.get("messages", []))[-10:])
   if st.session_state.pending_options:
       st.session_state.pending_turn["assistant"] = list(st.session_state.pending_options)
       st.session_state.pending_turn["reasoning"] = st.session_state.get("last_reasoning", "")
   st.rerun()
