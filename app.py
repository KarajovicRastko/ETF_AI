import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv


BASE_DIR = Path(__file__).parent
SKILLS_DIR = BASE_DIR / ".NewSkills"
STUDIRANJE_PATH = SKILLS_DIR / "Studiranje.md"
WORKERS_PATH = SKILLS_DIR / "Workers.md"

DEFAULT_PROMPTS = [
    "Ko je profesor Mladen Koprivica?",
    "Koji predmeti su na drugoj godini smer Telekomunikacije?",
    "Ko predaje Osnove Elektrotehnike 2?",
]

STOP_WORDS = {
    "a",
    "i",
    "ili",
    "je",
    "ko",
    "koja",
    "koje",
    "koji",
    "na",
    "od",
    "o",
    "po",
    "sa",
    "se",
    "su",
    "sta",
    "sto",
    "u",
    "za",
    "predaje",
    "radi",
    "rade",
}

SERBIAN_CYRILLIC_TO_LATIN = str.maketrans(
    {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "ђ": "dj",
        "е": "e",
        "ж": "z",
        "з": "z",
        "и": "i",
        "ј": "j",
        "к": "k",
        "л": "l",
        "љ": "lj",
        "м": "m",
        "н": "n",
        "њ": "nj",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "ћ": "c",
        "у": "u",
        "ф": "f",
        "х": "h",
        "ц": "c",
        "ч": "c",
        "џ": "dz",
        "ш": "s",
        "А": "A",
        "Б": "B",
        "В": "V",
        "Г": "G",
        "Д": "D",
        "Ђ": "Dj",
        "Е": "E",
        "Ж": "Z",
        "З": "Z",
        "И": "I",
        "Ј": "J",
        "К": "K",
        "Л": "L",
        "Љ": "Lj",
        "М": "M",
        "Н": "N",
        "Њ": "Nj",
        "О": "O",
        "П": "P",
        "Р": "R",
        "С": "S",
        "Т": "T",
        "Ћ": "C",
        "У": "U",
        "Ф": "F",
        "Х": "H",
        "Ц": "C",
        "Ч": "C",
        "Џ": "Dz",
        "Ш": "S",
    }
)


@dataclass(frozen=True)
class KnowledgeChunk:
    source: str
    title: str
    text: str
    searchable_text: str


def normalize_text(value: str) -> str:
    latin = value.translate(SERBIAN_CYRILLIC_TO_LATIN).lower()
    latin = latin.replace("š", "s").replace("đ", "dj").replace("ž", "z")
    latin = latin.replace("č", "c").replace("ć", "c")
    return re.sub(r"[^a-z0-9]+", " ", latin)


def tokenize(value: str) -> list[str]:
    return [
        token
        for token in normalize_text(value).split()
        if (len(token) > 1 or token.isdigit()) and token not in STOP_WORDS
    ]


def read_markdown(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def strip_markdown_links(value: str) -> str:
    without_links = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    return re.sub(r"\s+", " ", without_links).strip()


def split_subjects(value: str) -> list[str]:
    subjects = []
    for subject in value.split(";"):
        cleaned = strip_markdown_links(subject)
        if cleaned:
            subjects.append(cleaned)
    return subjects


def subject_name(subject: str) -> str:
    if " - " in subject:
        return subject.split(" - ", 1)[1].strip()
    return subject.strip()


def split_studiranje(markdown: str) -> list[KnowledgeChunk]:
    chunks: list[KnowledgeChunk] = []
    current_title = "Studiranje"
    current_lines: list[str] = []

    for line in markdown.splitlines():
        if line.startswith("### "):
            if current_lines:
                chunks.append(make_chunk("Studiranje.md", current_title, "\n".join(current_lines)))
            current_title = line.removeprefix("### ").strip()
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_lines:
        chunks.append(make_chunk("Studiranje.md", current_title, "\n".join(current_lines)))

    return chunks


def split_workers(markdown: str) -> list[KnowledgeChunk]:
    chunks: list[KnowledgeChunk] = []
    subject_workers: dict[str, dict[str, object]] = {}

    for line in markdown.splitlines():
        if not line.startswith("|") or line.startswith("| ---"):
            continue

        columns = [column.strip() for column in line.strip("|").split("|")]
        if len(columns) < 11 or columns[1] == "Име":
            continue

        academic_title = strip_markdown_links(columns[0])
        first_name = strip_markdown_links(columns[1])
        last_name = strip_markdown_links(columns[2])
        position = strip_markdown_links(columns[3])
        department = strip_markdown_links(columns[4])
        email = strip_markdown_links(columns[5]).replace("mailto:", "")
        phone = strip_markdown_links(columns[6])
        employee_type = strip_markdown_links(columns[8])
        latin_name = strip_markdown_links(columns[9]) or f"{first_name} {last_name}".strip()
        subjects = split_subjects(columns[10])

        subject_text = "\n".join(f"- {subject}" for subject in subjects) or "- Nema navedenih predmeta"
        employee_text = f"""
Zaposleni: {latin_name}
Ime i prezime cirilica: {first_name} {last_name}
Titula: {academic_title or "Nije navedeno"}
Zvanje/Radno mesto: {position or "Nije navedeno"}
Organizaciona jedinica/Katedra: {department or "Nije navedeno"}
Tip zaposlenog: {employee_type or "Nije navedeno"}
Email: {email or "Nije naveden"}
Telefon: {phone or "Nije naveden"}
Predmeti:
{subject_text}
""".strip()

        chunks.append(make_chunk("Workers.md", latin_name or "Zaposleni", employee_text))

        for subject in subjects:
            name = subject_name(subject)
            key = normalize_text(name)
            if not key:
                continue
            record = subject_workers.setdefault(key, {"name": name, "workers": []})
            record["workers"].append(
                f"{latin_name} - {academic_title} {position}, {department}".strip()
            )

    for record in subject_workers.values():
        workers = "\n".join(f"- {worker}" for worker in sorted(set(record["workers"])))
        subject_text = f"""
Predmet: {record["name"]}
Ko predaje / ko radi na predmetu:
{workers}
""".strip()
        chunks.append(make_chunk("Workers.md", f"Predmet: {record['name']}", subject_text))

    return chunks


def make_chunk(source: str, title: str, text: str) -> KnowledgeChunk:
    return KnowledgeChunk(
        source=source,
        title=title,
        text=text,
        searchable_text=f"{text}\n{normalize_text(text)}",
    )


@st.cache_data(show_spinner=False)
def load_knowledge() -> list[KnowledgeChunk]:
    studying = read_markdown(STUDIRANJE_PATH)
    workers = read_markdown(WORKERS_PATH)
    return split_studiranje(studying) + split_workers(workers)


def score_chunk(chunk: KnowledgeChunk, query_tokens: list[str], question: str) -> int:
    score = 0
    searchable = normalize_text(chunk.searchable_text)
    title = normalize_text(chunk.title)
    query_phrase = " ".join(query_tokens)
    normalized_question = normalize_text(question)
    asks_about_teacher = any(token in normalized_question for token in ["profesor", "nastavnik", "asistent"])
    asks_who_teaches = any(token in normalized_question for token in ["predaje", "nastavu"])

    for token in query_tokens:
        if token in title:
            score += 30
        score += min(searchable.count(token), 8)

    if query_phrase and query_phrase in title:
        score += 120
    if query_phrase and query_phrase in searchable:
        score += 50

    if chunk.source == "Workers.md" and (asks_about_teacher or asks_who_teaches):
        score += 40
    if title.startswith("predmet") and asks_who_teaches:
        score += 100
    if all(token in searchable for token in query_tokens):
        score += 30

    return score


def retrieve_context(question: str, chunks: list[KnowledgeChunk], limit: int = 8) -> list[KnowledgeChunk]:
    query_tokens = tokenize(question)
    if not query_tokens:
        return []

    scored = [
        (score_chunk(chunk, query_tokens, question), chunk)
        for chunk in chunks
    ]
    scored = [(score, chunk) for score, chunk in scored if score > 0]
    scored.sort(key=lambda item: item[0], reverse=True)
    return [chunk for _, chunk in scored[:limit]]


def build_prompt(question: str, context_chunks: list[KnowledgeChunk]) -> str:
    context = format_context(context_chunks)
    return f"""
Ti si AI asistent Elektrotehnickog fakulteta Univerziteta u Beogradu.

Pravila:
- Odgovaraj samo na pitanja o ETF-u, studiranju, predmetima, modulima i zaposlenima.
- Koristi iskljucivo informacije iz konteksta ispod.
- Ako pitanje nije vezano za fakultet ili odgovor nije u kontekstu, reci: "Nemam tu informaciju u dostupnim podacima o ETF-u."
- Odgovaraj na srpskom jeziku, jasno i kratko.
- Kada je korisno, navedi predmet, zvanje, katedru, email ili telefon koji postoje u kontekstu.

Kontekst:
{context}

Pitanje:
{question}
""".strip()


def format_context(context_chunks: list[KnowledgeChunk], max_chars: int = 45000) -> str:
    context_parts = []
    current_size = 0

    for chunk in context_chunks:
        chunk_text = f"Source: {chunk.source} | Section: {chunk.title}\n{chunk.text}"
        remaining = max_chars - current_size
        if remaining <= 0:
            break
        if len(chunk_text) > remaining:
            chunk_text = chunk_text[:remaining]
        context_parts.append(chunk_text)
        current_size += len(chunk_text)

    return "\n\n".join(context_parts)


def call_gemini(prompt: str, model_name: str, api_key: str) -> str:
    from google import genai

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(model=model_name, contents=prompt)
    return response.text or "Nemam odgovor iz modela."


def call_cursor(prompt: str, api_key: str, model_name: str, command: str) -> str:
    result = subprocess.run(
        [
            command,
            "agent",
            "--api-key",
            api_key,
            "--model",
            model_name,
            "--mode",
            "ask",
            "--print",
            "--output-format",
            "text",
            prompt,
        ],
        text=True,
        capture_output=True,
        timeout=120,
        cwd=BASE_DIR,
        encoding="utf-8",
        errors="replace",
    )

    if result.returncode != 0:
        details = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(details or f"Cursor returned exit code {result.returncode}.")

    return result.stdout.strip() or "Cursor nije vratio odgovor."


def answer_question(question: str, chunks: list[KnowledgeChunk]) -> str:
    context_chunks = retrieve_context(question, chunks)
    if not context_chunks:
        return "Nemam tu informaciju u dostupnim podacima o ETF-u."

    prompt = build_prompt(question, context_chunks)
    provider = os.getenv("AI_PROVIDER", "gemini").strip().lower()

    if provider == "gemini":
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite").strip()
        if not api_key or api_key == "your_api_key_here":
            return "GEMINI_API_KEY nije podesen u .env fajlu."
        return call_gemini(prompt, model_name, api_key)

    if provider == "cursor":
        api_key = os.getenv("CURSOR_API_KEY", "").strip()
        model_name = os.getenv("CURSOR_MODEL", "gpt-5.5-medium").strip()
        command = os.getenv("CURSOR_COMMAND", "agent").strip()
        if not api_key or api_key == "your_cursor_api_key_here":
            return "CURSOR_API_KEY nije podesen u .env fajlu."
        try:
            return call_cursor(prompt, api_key, model_name, command)
        except FileNotFoundError:
            return f"Cursor komanda nije pronadjena: {command}"
        except subprocess.TimeoutExpired:
            return "Cursor nije odgovorio u predvidjenom vremenu."
        except RuntimeError as exc:
            return f"Cursor greska: {exc}"

    return f"Nepoznat AI_PROVIDER: {provider}. Koristi 'gemini' ili 'cursor'."


def render_sidebar() -> None:
    provider = os.getenv("AI_PROVIDER", "gemini").strip().lower()
    st.sidebar.header("Podesavanja")
    st.sidebar.write(f"Provider: `{provider}`")

    if provider == "gemini":
        model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite").strip()
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        st.sidebar.write(f"Model: `{model_name}`")
        st.sidebar.write("API key: configured" if api_key and api_key != "your_api_key_here" else "API key: missing")
    elif provider == "cursor":
        model_name = os.getenv("CURSOR_MODEL", "gpt-5.5-medium").strip()
        api_key = os.getenv("CURSOR_API_KEY", "").strip()
        st.sidebar.write(f"Cursor model: `{model_name}`")
        st.sidebar.write("Cursor API key: configured" if api_key and api_key != "your_cursor_api_key_here" else "Cursor API key: missing")
    else:
        st.sidebar.warning("AI_PROVIDER mora biti 'gemini' ili 'cursor'.")


def main() -> None:
    load_dotenv(BASE_DIR / ".env")
    st.set_page_config(page_title="ETF AI Asistent", page_icon="ETF", layout="centered")

    st.title("ETF AI Asistent")
    st.caption("Postavi pitanje o studiranju, predmetima ili zaposlenima na Elektrotehnickom fakultetu u Beogradu.")

    render_sidebar()
    chunks = load_knowledge()

    if "messages" not in st.session_state:
        st.session_state.messages = []

    st.subheader("Postavi pitanje")
    with st.form("custom_question_form", clear_on_submit=True):
        custom_question = st.text_input(
            "Unesi svoje pitanje za ETF asistenta",
            placeholder="Npr. Ko predaje Osnove elektrotehnike 2?",
        )
        submitted = st.form_submit_button("Posalji")

    st.subheader("Preporucena pitanja")
    columns = st.columns(len(DEFAULT_PROMPTS))
    selected_prompt = None
    for column, prompt in zip(columns, DEFAULT_PROMPTS, strict=True):
        if column.button(prompt, use_container_width=True):
            selected_prompt = prompt

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    question = (custom_question if submitted and custom_question else None) or selected_prompt or st.chat_input("Pitaj ETF asistenta...")
    if not question:
        return

    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.spinner("Trazim odgovor u ETF podacima..."):
            response = answer_question(question, chunks)
        st.markdown(response)

    st.session_state.messages.append({"role": "assistant", "content": response})


if __name__ == "__main__":
    main()
