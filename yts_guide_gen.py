#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YTS Guide 生成模块

- 内置原版韩文 제작 가이드（来自 [YouTube Shopping]알리익스프레스 콘텐츠 제작 가이드.docx）
- 接 AI（OpenAI 兼容接口，默认千问，Secrets 可换智谱等）：
  · Guide 追加「定制选题 & 爆款逻辑」韩文章节（选品前不给具体脚本）
  · 选品后「视频脚本推荐」：结合商品出 3 个爆款脚本框架（只给框架不写全台词）
- 组装完整 guide（原版 + AI 章节），支持导出 Word（python-docx）

Key 读取顺序：环境变量/Secrets DASHSCOPE_API_KEY -> 本地 dashscope_key_local.py（不入库）
模型名可用 DASHSCOPE_MODEL 覆盖（默认 qwen-plus）；接口地址可用 DASHSCOPE_URL
覆盖（任何 OpenAI 兼容服务都行）。三者都在 Streamlit Cloud Secrets 改，不用动代码。
"""
import io
import os
import re

import requests

DASHSCOPE_URL = os.environ.get(
    "DASHSCOPE_URL",
    "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")
DEFAULT_MODEL = "qwen-plus"


def get_model() -> str:
    """模型名：Secrets/环境变量 DASHSCOPE_MODEL 优先，未设置用 qwen-plus。
    调用时读取，Secrets 改完重启即生效。"""
    return os.environ.get("DASHSCOPE_MODEL", "").strip() or DEFAULT_MODEL

# ---------------------------------------------------------------------------
# 原版 가이드（韩文，忠实于 Word 原件）
# ---------------------------------------------------------------------------
ORIGINAL_GUIDE_MD = """# [YouTube Shopping] 알리익스프레스 콘텐츠 제작 가이드

## 1. 콘텐츠
- **내용**: 방향성에 맞게 제품을 직접 선정한 후, 각 제품의 특징과 추천 이유가 자연스럽게 포함되도록 구성
- **방향성**: 애용템/추천템 소개 · 언박싱 및 제품 리뷰 · 일상 속 제품 활용 꿀팁
- **제품**: 2-5개 희망. 유튜브 쇼핑 태그 등록 상품 중 희망 상품 직접 선정 → **희망 상품 선정 후 상품 링크 전달** → 알리 검수 진행 → 최종 확정된 상품 직접 구매 후 콘텐츠 제작
- **형식**: 쇼츠 or 롱폼（쇼츠 15초 이상, 롱폼 3분 이상）

## 2. 코드 혜택 (Code: YTSKOL)
- **이용 안내**: $10 이상 구매 시 $2 할인 받기
- **유효 기간**: KST 7/21 00:00 - 9/30 23:59

## 3. 심의 안내
- 콘텐츠 제작 완료 후, 업로드 전 **반드시 영상을 전달** 부탁드립니다.
- **심의 제출 형식**: 영상은 반드시 **YouTube 영상 링크** 형태로 제출 부탁드립니다.（비공개/목록 미게시 링크 가능）
- 내부 심의 확인 항목: 광고 관련 법규 준수 여부, 상품 정보 및 혜택 정보의 정확성 등
- 수정이 필요한 경우 피드백 전달 → 수정 완료 후 재심의 진행
- **힌트**: 보다 원활한 심의를 위해 영상 내에 타 플랫폼의 명칭이 포함된 화면이 노출되지 않도록 유의해 주세요:)

## 4. 필수 사항
- 유튜브 **쇼핑 태그 기능 활용** 필수
- 유튜브 **유료광고 표기** 필수
- **코드 혜택 정보 포함** 필수（코드: YTSKOL / 유효 기간 / 이용 안내）
- **게시 시 전용 해시태그** 부착 필수 — 전용 태그는 확정되는 대로 별도 안내 예정

## 5. 참고 사항
- **제목**: 제품 선정 후 자유롭게 구성 가능
- **썸네일**: 제품과 사용 장면이 잘 드러나는 방향 권장
- **정산 방식**: 판매 수익은 유튜브를 통해 직접 정산 / 제작비는 별도 지급
- **참고 영상**: 하봄 https://youtube.com/shorts/xIetj_6u_uo · 푸짐스 https://youtube.com/shorts/S3BT8PiziC0 · 켈리아 https://www.youtube.com/shorts/W6bs2y-ab70

## 6. 예상 진행 일정（전체 약 1개월）
- ① 협업 의향 확정（협업 여부 및 예상 업로드 일정 확인）
- ② 협업 확정 후 5일 이내: 희망 상품 리스트 및 선정 이유 전달 → 내부 확인 후 상품 구매 진행
- ③ 제품 수령 완료 후 수령 여부 공유
- ④ 제품 수령 후 3~5일 이내: 기획안 전달 및 피드백
- ⑤ 기획안 확정 후 촬영 및 편집 진행
- ⑥ 매월 16일 이전: 업로드 예정 영상 전달
- ⑦ 내부 심의（영업일 기준 약 3일）→ 수정 필요 시 피드백 전달
- ⑧ 심의 통과 시 21일 업로드 / 미통과 시 수정본 재심의（약 1영업일）
- ⑨ 매월 21일 영상 업로드
- ※ 제작비는 영상 업로드 후 대행사를 통해 별도 계약 및 정산 진행 예정
"""

AI_SECTION_TITLE = "## 7. 콘텐츠 방향 & 바이럴(爆款) 논리 제안 (AI)"

SYSTEM_PROMPT = (
    "당신은 AliExpress 한국 YouTube Shopping 프로젝트의 시니어 콘텐츠 디렉터입니다. "
    "기존 제작 가이드 뒤에 덧붙일 「콘텐츠 방향 & 바이럴(爆款) 논리 제안」 섹션을 한국어로 작성합니다. "
    "전제: 제공된 상품 이름/링크가 있으면 반드시 구체적으로 반영하고, 상품이 아직 없으면 "
    "콘텐츠 카테고리·판매(带货) 카테고리 특성 기반으로 제안합니다. "
    "규칙: 1) 인플루언서의 콘텐츠 카테고리, 판매 카테고리, 채널 스타일, 구독자 규모를 결합한 "
    "맞춤형 주제 3개를 제안 — 뻔한 일반론 금지, 이 인플루언서라서 가능한 구체 주제로. "
    "2) 각 주제마다: 콘텐츠 방향(2-3문장), 왜 이 인플루언서에게 맞는지, 상품을 자연스럽게 녹이는 방법. "
    "3) 바이럴 논리: 훅 설계(그대로 써도 되는 한국어 훅 예문 주제별 1-2개 반드시 포함), "
    "첫 3초 시청 유지 설계, 감정 트리거, 전환 포인트. "
    "4) 전환 포인트는 유튜브 쇼핑 태그 클릭 & 할인 코드 YTSKOL($10 이상 구매 시 $2 할인)로 "
    "자연스럽게 이어지게 한 줄로 제시. "
    "5) 제목은 클릭을 유도하는 구체 예시 5개 + 해시태그 세트 함께 제시. "
    "6) 심의 규칙 준수: 유료광고 표기, 타 플랫폼 명칭 노출 금지, 코드 혜택 정보 포함, 쇼핑 태그 필수. "
    "7) 한국어로만 출력, 마크다운 형식(## / - / **굵은글자**) 사용, 서론 없이 바로 본문 출력. "
    "8) 분량은 충분히 상세하게 — 인플루언서가 이 문서만으로 촬영 기획을 시작할 수 있을 수준으로."
)

USER_PROMPT_TPL = """인플루언서 정보:
- 昵称(닉네임): {name}
- 채널 URL: {channel_url}
- 内容垂类(콘텐츠 카테고리): {category}
- 带货垂类(판매 카테고리): {sales_category}
- 粉丝数(구독자): {subscribers}
- 报价(제작비): {price}
- 选品清单(선정 희망 상품):
{products}
- 计划上线(업로드 예정): {plan_month}
- 备注(내부 참고 사항): {notes}

추가 요청 사항:
{requirements}

아래 구조대로 최대한 구체적이고 상세하게 출력하세요:
## A. 맞춤형 콘텐츠 주제 제안（3개）
각 주제마다 **주제명** / **콘텐츠 방향**(2-3문장) / **왜 이 인플루언서에게 맞는가** / **상품 녹이는 방법** 포함
## B. 주제별 바이럴(爆款) 논리
각 주제마다 **훅 설계**(그대로 쓸 수 있는 한국어 훅 예문 1-2개 포함) / **시청 유지 설계**(전개 순서) / **감정 트리거** / **전환 포인트**(쇼핑 태그 & 코드 YTSKOL 연결 한 줄) 포함
## C. 제목 예시 5개 & 해시태그 세트
## D. 심의·필수사항 체크리스트（유료광고 표기 / 타 플랫폼 명칭 노출 금지 / 코드 YTSKOL 정보 포함 / 쇼핑 태그 / 전용 해시태그）
"""


def _fmt_num(v) -> str:
    """粉丝数等数字千分位格式化，空值显示 -"""
    try:
        n = int(float(v))
        return f"{n:,}" if n > 0 else "-"
    except (TypeError, ValueError):
        return str(v).strip() if v else "-"


def _fmt_price(v) -> str:
    """报价（韩币）格式化"""
    try:
        n = int(float(v))
        return f"{n:,}원" if n > 0 else "(미정)"
    except (TypeError, ValueError):
        return "(미정)"


def _fmt_products(collab: dict) -> str:
    """选品信息：商品子表的名称/类目/ID 为主，product_list 链接作补充"""
    lines = []
    for p in collab.get("products") or []:
        name = (p.get("name") or "").strip()
        pid = (p.get("pid") or "").strip()
        cat = (p.get("p_category") or "").strip()
        if name or pid:
            bits = [b for b in (name or "(이름 미입력)",
                                f"카테고리: {cat}" if cat else "",
                                f"상품ID: {pid}" if pid else "") if b]
            lines.append("  - " + " / ".join(bits))
    for link in collab.get("product_list") or []:
        link = str(link).strip()
        if link:
            lines.append(f"  - 링크: {link}")
    return "\n".join(lines)


def get_api_key() -> str:
    key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if key:
        return key
    try:
        from dashscope_key_local import DASHSCOPE_API_KEY  # noqa: 本地调试用，不入库
        return (DASHSCOPE_API_KEY or "").strip()
    except ImportError:
        return ""


def build_prompt(collab: dict, requirements: str = "") -> list:
    products = _fmt_products(collab)
    user = USER_PROMPT_TPL.format(
        name=collab.get("channel_name") or collab.get("name") or "-",
        channel_url=collab.get("channel_url") or "-",
        category=collab.get("category") or "-",
        sales_category=collab.get("sales_category") or "-",
        subscribers=_fmt_num(collab.get("followers") or collab.get("subscribers")),
        price=_fmt_price(collab.get("price")),
        products=products or "  - (아직 없음 — 콘텐츠/판매 카테고리 특성 기반으로 강전환 방향으로 제안)",
        plan_month=collab.get("plan_month") or "-",
        notes=(collab.get("notes") or "").strip() or "-",
        requirements=requirements.strip() or "(없음, 기본 강전환 방향)",
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


# ---------------------------------------------------------------------------
# 选品后：视频脚本推荐（3 个爆款脚本框架，不写全台词）
# ---------------------------------------------------------------------------
SCRIPT_SYSTEM_PROMPT = (
    "당신은 AliExpress 한국 YouTube Shopping 프로젝트의 시니어 쇼츠/롱폼 각본가입니다. "
    "확정된 선정 상품과 인플루언서의 카테고리/스타일을 결합해 「바이럴 스크립트 프레임워크」 3개를 한국어로 작성합니다. "
    "원칙: 대본 전체(逐字稿)를 쓰지 않는다 — 방향 + 필수 요소 + 참고 화법만 제공한다. "
    "규칙: 1) 각 프레임워크마다: 주제 각도(왜 이 각도가 먹히는지), 형식(쇼츠/롱폼)과 길이, "
    "초 단위 타임라인 구조(예: 0-3초 훅 / 3-10초 페인포인트·장면 / 10-25초 제품 등장+셀링포인트 / …). "
    "2) 훅 예문과 CTA 예문은 그대로 참고해도 되는 한국어 한 줄 문장으로 제시하고, "
    "그 외 대사는 인플루언서가 자유롭게 채우도록 둔다. "
    "3) 상품 이름/카테고리에서 셀링포인트(가성비/공간 절약/사용 편의/비주얼 등)를 추론해 "
    "인플루언서 콘텐츠 스타일과 결합 — 어떤 제품을 몇 초에 등장시켜 어떤 특징을 강조할지 명시. "
    "4) 전환 포인트: 유튜브 쇼핑 태그 클릭 유도 + 할인 코드 YTSKOL($10 이상 구매 시 $2 할인) 언급 시점 명시. "
    "5) 심의 규칙 준수: 유료광고 표기, 타 플랫폼 명칭 노출 금지. "
    "6) 한국어로만 출력, 마크다운 형식(## / - / **굵은글자**) 사용, 서론 없이 바로 본문 출력. "
    "7) 세 프레임워크는 서로 다른 각도로(예: 언박싱/활용 꿀팁/비교 또는 하루 루틴 등), 분량은 충분히 상세하게."
)

SCRIPT_USER_PROMPT_TPL = """인플루언서 정보:
- 昵称(닉네임): {name}
- 内容垂类(콘텐츠 카테고리): {category}
- 带货垂类(판매 카테고리): {sales_category}
- 粉丝数(구독자): {subscribers}

확정 선정 상품(选品清单):
{products}

추가 요청 사항:
{requirements}

아래 구조대로 출력하세요. 각 프레임워크는 충분히 구체적으로 작성:
## 스크립트 프레임워크 1. 「주제명」
## 스크립트 프레임워크 2. 「주제명」
## 스크립트 프레임워크 3. 「주제명」
각 프레임워크 안에 다음을 모두 포함하세요:
- **각도**: 왜 이 각도가 이 인플루언서·상품 조합에서 먹히는지 한 문장
- **형식·길이**: 쇼츠/롱폼 + 목표 초 수
- **타임라인 구조**: 초 단위 구간 구분(예: 0-3초 훅 / 3-10초 페인포인트 / 10-25초 제품 등장+셀링포인트 / 25-40초 사용 효과 / 40-50초 코드 혜택 / 50-60초 CTA)
- **훅 예문**: 그대로 참고 가능한 한국어 한 문장
- **제품 등장 시점 & 셀링포인트**: 어떤 제품을 몇 초에, 어떤 특징을 강조
- **전환 포인트**: 쇼핑 태그 클릭 유도 + 코드 YTSKOL 언급 시점
- **CTA 예문**: 한국어 한 문장"""


def build_script_prompt(collab: dict, requirements: str = "") -> list:
    """选品后脚本推荐提示词：商品清单 + 网红垂类/风格 → 3 个爆款脚本框架"""
    products = _fmt_products(collab)
    user = SCRIPT_USER_PROMPT_TPL.format(
        name=collab.get("channel_name") or collab.get("name") or "-",
        category=collab.get("category") or "-",
        sales_category=collab.get("sales_category") or "-",
        subscribers=_fmt_num(collab.get("followers") or collab.get("subscribers")),
        products=products or "  - (없음)",
        requirements=requirements.strip() or "(없음)",
    )
    return [
        {"role": "system", "content": SCRIPT_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def call_dashscope(messages: list, timeout: int = 300) -> str:
    """调用 AI（OpenAI 兼容接口），返回生成文本；无 key / 出错时抛 RuntimeError(友好文案)。
    大模型（如 glm-5.3）思考+生成可能耗时几分钟，timeout 放宽到 300 秒。"""
    key = get_api_key()
    if not key:
        raise RuntimeError(
            "未配置 DASHSCOPE_API_KEY · DASHSCOPE_API_KEY가 설정되지 않았습니다. "
            "请在主站 Cloud Secrets 添加 DASHSCOPE_API_KEY（百炼/智谱等控制台获取）")
    try:
        resp = requests.post(
            DASHSCOPE_URL,
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"},
            json={"model": get_model(), "messages": messages, "temperature": 0.8,
                  "max_tokens": 8192},
            timeout=timeout,
        )
    except requests.exceptions.Timeout:
        raise RuntimeError(
            f"AI 接口 {timeout} 秒内没返回结果（大模型思考较慢，属正常现象）。"
            "请稍后重试点一次；若经常超时，可在 Secrets 把 DASHSCOPE_MODEL 换成更快的模型")
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"AI 接口连接失败（{type(e).__name__}），请稍后重试")
    if resp.status_code != 200:
        raise RuntimeError(f"AI 接口返回 {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"AI 返回结构异常: {str(data)[:300]}") from e


def assemble_full_guide(script_md: str) -> str:
    return ORIGINAL_GUIDE_MD.rstrip() + "\n\n" + AI_SECTION_TITLE + "\n\n" + script_md.strip() + "\n"


# ---------------------------------------------------------------------------
# Markdown(子集) -> Word
# ---------------------------------------------------------------------------
_BOLD = re.compile(r"\*\*(.+?)\*\*")


def _add_para_with_bold(doc, text, style=None):
    para = doc.add_paragraph(style=style)
    pos = 0
    for m in _BOLD.finditer(text):
        if m.start() > pos:
            para.add_run(text[pos:m.start()])
        para.add_run(m.group(1)).bold = True
        pos = m.end()
    if pos < len(text):
        para.add_run(text[pos:])
    return para


def md_to_docx(md: str, title: str = "") -> bytes:
    from docx import Document
    from docx.shared import Pt
    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name = "Malgun Gothic"
    normal.font.size = Pt(10.5)
    for line in md.splitlines():
        s = line.rstrip()
        if not s.strip():
            continue
        if s.startswith("### "):
            _add_para_with_bold(doc, s[4:], style="Heading 3")
        elif s.startswith("## "):
            _add_para_with_bold(doc, s[3:], style="Heading 2")
        elif s.startswith("# "):
            _add_para_with_bold(doc, s[2:], style="Heading 1")
        elif s.lstrip().startswith("- "):
            _add_para_with_bold(doc, s.lstrip()[2:], style="List Bullet")
        else:
            _add_para_with_bold(doc, s)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
