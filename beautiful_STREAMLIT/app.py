import streamlit as st

from wikipedia_extractor_core import (
    Wikipedia,
    block_counts,
    format_txt,
    load_hit,
    numbered_filename,
    search_topic,
)

st.set_page_config(page_title="Wikipedia Extractor", layout="wide")

# ---------- session_state init ----------
DEFAULTS = {
    "topic": None,
    "article": None,
    "hits": [],
    "titles": [],
    "selected": [],
    "sections": [],
    "error": None,
    "downloaded_filenames": [],
}
for key, value in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = list(value) if isinstance(value, list) else value

# corrupt state: sections/titles without an article
if st.session_state.article is None and (
    st.session_state.titles or st.session_state.sections
):
    st.session_state.titles = []
    st.session_state.selected = []
    st.session_state.sections = []
    st.session_state.downloaded_filenames = []
    st.rerun()

wiki = Wikipedia()


def set_article(article):
    st.session_state.article = article
    st.session_state.titles = [s["title"] for s in article.sections]
    st.session_state.selected = []
    st.session_state.sections = []
    st.session_state.hits = []
    st.session_state.error = None


def mark_downloaded(filename):
    st.session_state.downloaded_filenames.append(filename)


# ---------- sidebar ----------
with st.sidebar:
    st.header("Wikigrab")
    st.caption("Pull selected sections of an English Wikipedia article into a clean .txt file.")
    if st.button("Start Over"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

# ---------- title + guide ----------
st.title("Wikipedia Article Extractor")
with st.expander("How to use this app"):
    st.markdown(
        "1. Enter a topic and click **Search**.\n"
        "2. Select the sections you want from the multiselect.\n"
        "3. Click **Extract** to preview them.\n"
        "4. Click **Download .txt** to save the file to your device."
    )

# ---------- progress indicator ----------
done = [
    bool(st.session_state.topic),
    bool(st.session_state.titles),
    bool(st.session_state.sections),
    bool(st.session_state.downloaded_filenames),
]
for col, label, ok in zip(st.columns(4), ["Search", "Select", "Extract", "Download"], done):
    col.caption(("✅ " if ok else "⬜ ") + label)

# ---------- stage 1: search ----------
with st.form("search_form"):
    topic_input = st.text_input("Enter a topic", placeholder="e.g. Japan")
    submitted = st.form_submit_button("Search")

if submitted:
    topic = topic_input.strip()
    if not topic:
        st.warning("The topic can't be empty.")
    else:
        st.session_state.topic = topic
        st.session_state.article = None
        st.session_state.titles = []
        st.session_state.selected = []
        st.session_state.sections = []
        st.session_state.hits = []
        st.session_state.error = None
        with st.spinner("Searching Wikipedia ..."):
            article, hits, error = search_topic(wiki, topic)
        if error:
            st.session_state.error = error
        elif article is not None:
            set_article(article)
        else:
            st.session_state.hits = hits

if st.session_state.error:
    st.error(st.session_state.error)

# no exact match: let the user pick a candidate
if st.session_state.hits and st.session_state.article is None:
    st.info("No exact match. Did you mean:")
    options = {title: url for title, url in st.session_state.hits}
    choice = st.radio("Candidates", list(options.keys()), key="hit_choice")
    if st.button("Load this article"):
        with st.spinner("Loading article ..."):
            article, error = load_hit(wiki, options[choice])
        if error:
            st.session_state.error = error
            st.rerun()
        else:
            set_article(article)
            st.rerun()

article = st.session_state.article
if article is not None:
    st.success(f"Found: {article.title} ({len(article.sections)} sections)")
    st.write(article.url)
    if article.is_disambiguation():
        st.warning("That's a disambiguation page, try a more specific title.")

    # ---------- stage 2: select ----------
    if len(st.session_state.titles) < 1:
        st.warning("This article has no usable sections.")
    else:
        labels = {}
        for s in article.sections:
            c = block_counts(s)
            labels[s["title"]] = (
                f"{s['title']}  ({c['paragraph']}p {c['list']}l {c['table']}t {c['subheading']}h)"
            )
        st.caption("p = paragraphs, l = lists, t = tables, h = subheadings")
        st.session_state.selected = st.multiselect(
            "Select sections",
            options=st.session_state.titles,
            default=st.session_state.selected,
            format_func=lambda t: labels.get(t, t),
        )

        # ---------- stage 3: extract ----------
        if st.button("Extract"):
            if not st.session_state.selected:
                st.warning("Please select at least one section first.")
            else:
                by_title = {s["title"]: s for s in article.sections}
                st.session_state.sections = [
                    by_title[t] for t in st.session_state.selected if t in by_title
                ]

    # ---------- stage 4: preview ----------
    if st.session_state.sections:
        with st.container(border=True):
            for section in st.session_state.sections:
                st.markdown(f"### {section['title']}")
                if not section["blocks"]:
                    st.caption("(no extractable content)")
                for kind, content in section["blocks"]:
                    if kind == "paragraph":
                        st.write(content)
                    elif kind == "h3":
                        st.markdown(f"#### {content}")
                    elif kind == "h4":
                        st.markdown(f"##### {content}")
                    elif kind in ("ul", "ol"):
                        for n, item in enumerate(content, start=1):
                            marker = "-" if kind == "ul" else f"{n}."
                            st.markdown(f"{marker} {item}")
                    elif kind == "table":
                        st.dataframe(content)

        # ---------- download ----------
        proposed = article.default_filename()
        unique = numbered_filename(proposed, st.session_state.downloaded_filenames)
        if proposed in st.session_state.downloaded_filenames:
            st.warning(
                "You already downloaded a file with this name in this session. "
                f"Downloading again will name it {unique}."
            )
        st.download_button(
            label="Download .txt",
            data=format_txt(article, st.session_state.sections),
            file_name=unique,
            mime="text/plain",
            key="download_btn",
            on_click=mark_downloaded,
            args=(unique,),
        )

st.caption("Content from Wikipedia, CC BY-SA 4.0.")

st.write(st.session_state)  # debug
