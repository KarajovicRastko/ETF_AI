import re
from dataclasses import dataclass
from pathlib import Path

import requests
import streamlit as st


# Base paths for the app and the knowledge files used for retrieval.
BASE_DIR = Path(__file__).parent
API_URL = "https://api.ukisai.academy"
DEFAULT_MODEL = "qwen3-80b"

SKILLS_DIR = BASE_DIR / ".NewSkills"
STUDIRANJE_PATH = SKILLS_DIR / "Studiranje.md"
WORKERS_PATH = SKILLS_DIR / "Workers.md"

# System instructions sent to the LLM so it answers only from the provided ETF knowledge context.
SYSTEM_PROMPT = """
Ti si AI asistent Elektrotehnickog fakulteta Univerziteta u Beogradu.

Pravila:
- Ti si ETF AI 
-Odgovaraj samo na pitanja o ETF-u, studiranju, predmetima, modulima i zaposlenima.
- Koristi iskljucivo informacije iz konteksta koji korisnik dostavlja u poruci (odeljak Kontekst).
- Ako pitanje nije vezano za fakultet ili odgovor nije u kontekstu, reci: "Nemam tu informaciju u dostupnim podacima o ETF-u."
- Odgovaraj na srpskom jeziku, jasno i kratko.
- Kada je korisno, navedi predmet, zvanje, katedru, email ili telefon koji postoje u kontekstu.
""".strip()

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


# Represents one searchable piece of ETF knowledge extracted from markdown files.
@dataclass(frozen=True)
class KnowledgeChunk:
    source: str
    title: str
    text: str
    searchable_text: str


# Text normalization helpers used to make searches and matching more robust.
def normalize_text(value: str) -> str:
    latin = value.translate(SERBIAN_CYRILLIC_TO_LATIN).lower()
    latin = latin.replace("š", "s").replace("đ", "dj").replace("ž", "z")
    latin = latin.replace("č", "c").replace("ć", "c")
    return re.sub(r"[^a-z0-9]+", " ", latin)


def tokenize(value: str) -> list[str]:
    # Split text into useful words while removing stop words and short noise tokens.
    return [
        token
        for token in normalize_text(value).split()
        if (len(token) > 1 or token.isdigit()) and token not in STOP_WORDS
    ]


# Reads raw markdown knowledge files from disk.
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


# Parses the Studiranje markdown file into smaller knowledge chunks for retrieval.
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


# Parses the Workers markdown file into worker and subject-related knowledge chunks.
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


# Creates a chunk with both original text and normalized searchable text.
def make_chunk(source: str, title: str, text: str) -> KnowledgeChunk:
    return KnowledgeChunk(
        source=source,
        title=title,
        text=text,
        searchable_text=f"{text}\n{normalize_text(text)}",
    )


# Loads all ETF knowledge from markdown files and prepares it for search.
@st.cache_data(show_spinner=False)
def load_knowledge() -> list[KnowledgeChunk]:
    studying = read_markdown(STUDIRANJE_PATH)
    workers = read_markdown(WORKERS_PATH)
    return split_studiranje(studying) + split_workers(workers)


# Fetches available LLM models from the UKIS API for the sidebar selector.
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_ukis_models() -> list[str]:
    try:
        response = requests.get(f"{API_URL}/models", timeout=15)
        response.raise_for_status()
        data = response.json()
        models = data.get("models") or []
        return list(models) if isinstance(models, list) else []
    except (requests.RequestException, ValueError):
        return []


# Scores each knowledge chunk based on how relevant it is to the user's question.
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


# Selects the most relevant knowledge chunks for the current question.
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


# Formats the selected context into a compact prompt section for the LLM.
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


# Builds the final prompt that is sent to the model, including context and conversation history.
def build_user_message(question: str, context_chunks: list[KnowledgeChunk], conversation_history: list[dict] | None = None) -> str:
    context = format_context(context_chunks)
    
    # Build conversation history section
    history_text = ""
    if conversation_history:
        history_text = "\nPrethodna Konverzacija:\n"
        for msg in conversation_history:
            role = "Korisnik" if msg["role"] == "user" else "ETF Asistent"
            history_text += f"{role}: {msg['content']}\n"
        history_text += "\n"
    
    return f"""
Kontekst:
{context}{history_text}
Pitanje:
{question}
""".strip()


# Sends the prompt to the UKIS chat API and returns the model's reply.
def call_ukis_chat(system: str, message: str, model: str, timeout: int = 120) -> str:
    response = requests.post(
        f"{API_URL}/chat",
        json={"model": model, "system": system, "message": message},
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    text = data.get("response")
    if text is None:
        return "Server nije vratio polje 'response'."
    return str(text).strip() or "Nemam odgovor iz modela."


# Main answer flow: retrieve context, build the prompt, and call the LLM.
def answer_question(question: str, chunks: list[KnowledgeChunk], model: str, conversation_history: list[dict] | None = None, previous_context_chunks: list[KnowledgeChunk] | None = None) -> tuple[str, list[KnowledgeChunk]]:
    context_chunks = retrieve_context(question, chunks)
    
    # If no context found for this question, reuse relevant context from previous questions
    if not context_chunks and previous_context_chunks:
        context_chunks = previous_context_chunks
    
    if not context_chunks:
        return "Nemam tu informaciju u dostupnim podacima o ETF-u.", []

    user_message = build_user_message(question, context_chunks, conversation_history)
    try:
        response = call_ukis_chat(SYSTEM_PROMPT, user_message, model)
        return response, context_chunks
    except requests.HTTPError as exc:
        detail = ""
        if exc.response is not None:
            try:
                detail = exc.response.text[:500]
            except Exception:
                detail = str(exc.response.status_code)
        return f"UKIS API greska ({exc.response.status_code if exc.response else '?'}): {detail or str(exc)}", context_chunks
    except requests.RequestException as exc:
        return f"Greska pri pozivu UKIS servera: {exc}", context_chunks


# Renders the sidebar controls for choosing the LLM model.
def render_sidebar(models: list[str]) -> str:
    st.sidebar.header("Izaberi LLM model")

    choices = models if models else [DEFAULT_MODEL]
    default_index = 0
    if DEFAULT_MODEL in choices:
        default_index = choices.index(DEFAULT_MODEL)

    model = st.sidebar.selectbox("Modeli:", choices, index=min(default_index, len(choices) - 1))
    return model


# Main Streamlit entry point that builds the chat UI and handles question answering.
def main() -> None:
    st.set_page_config(page_title="ETF AI", page_icon="ETF", layout="centered")

    st.title("ETF AI")
    st.caption("Postavi pitanje o studiranju, predmetima ili zaposlenima na Elektrotehnickom fakultetu u Beogradu. (Trenutne dostupne inforamcije o predmetima i zaposlenima.)")

    models = fetch_ukis_models()
    selected_model = render_sidebar(models)

    chunks = load_knowledge()

    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "pending_prompt" not in st.session_state:
        st.session_state.pending_prompt = None
    if "last_context" not in st.session_state:
        st.session_state.last_context = None

    st.subheader("Preporucena pitanja")
    columns = st.columns(len(DEFAULT_PROMPTS))
    for column, prompt in zip(columns, DEFAULT_PROMPTS, strict=True):
        if column.button(prompt, use_container_width=True):
            st.session_state.pending_prompt = prompt

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # Always render chat input in the same position
    user_input = st.chat_input("Pitaj ETF asistenta...")
    question = st.session_state.pending_prompt or user_input
    
    if question:
        st.session_state.pending_prompt = None  # Clear after using
        st.session_state.messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)

        with st.chat_message("assistant"):
            with st.spinner("Trazim odgovor u ETF podacima..."):
                # Pass conversation history and previous context for follow-up questions
                response, context_chunks = answer_question(
                    question, 
                    chunks, 
                    selected_model, 
                    st.session_state.messages[:-1],
                    st.session_state.last_context
                )
                # Store context for potential follow-up questions
                st.session_state.last_context = context_chunks
            st.markdown(response)

        st.session_state.messages.append({"role": "assistant", "content": response})


if __name__ == "__main__":
    main()
