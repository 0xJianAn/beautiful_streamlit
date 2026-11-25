"""
wikipedia_extractor_core.py - logic layer for the wikigrab Streamlit app.

Contains the Wikipedia / Article classes and pure helpers only.
No input(), no print(), no file writing: the web app delivers the text
with st.download_button.

Needs: requests, beautifulsoup4, lxml
"""
from datetime import datetime

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://en.wikipedia.org"
HEADERS = {"User-Agent": "wikigrab/1.0"}
TIMEOUT = 10    # 5 was too short on campus wifi
MAX_CANDIDATES = 5
WRAP_WIDTH = 80
MAX_COLUMN = 30

# sections that aren't real article content45
SKIP_TITLES = [
    "References", "External links", "See also", "Notes",
    "Further reading", "Bibliography", "Citations", "Sources",
]

# stuff around the article that I never want in the output
NOISE_CLASSES = [
    "navbox", "infobox", "hatnote", "reflist", "thumb",
    "metadata", "sidebar", "ambox", "mw-empty-elt",
]

# characters windows doesn't allow in filenames (plus the comma, it looks messy)
BAD_FILENAME_CHARS = '\\/:*?"<>|,'


class Wikipedia:
    # the 2 requests I need: search and open an article

    def __init__(self, base_url=BASE_URL):
        self.base_url = base_url

    def get(self, url, params=None):
        # every network problem comes out as a ValueError with a readable message
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
        except requests.exceptions.Timeout:
            raise ValueError("the request timed out, try again")
        except requests.exceptions.ConnectionError:
            raise ValueError("can't reach Wikipedia - wifi? vpn?")
        except requests.exceptions.HTTPError as e:
            raise ValueError(f"got HTTP {e.response.status_code} back")
        except requests.exceptions.RequestException as e:
            # whatever else requests can throw
            raise ValueError(str(e))
        return r

    def search(self, topic):
        # returns (article, hits)
        # exact match: wikipedia jumps straight to the page, so (Article, [])
        # otherwise: (None, [(title, url), ...])
        response = self.get(self.base_url + "/w/index.php", params={"search": topic})
        soup = BeautifulSoup(response.text, "lxml")

        # exact match -> we get redirected to /wiki/Article_Title
        if "/wiki/" in response.url and "search=" not in response.url:
            return Article(response.url, soup), []

        hits = []
        for item in soup.find_all("li", class_="mw-search-result"):
            heading = item.find("div", class_="mw-search-result-heading")
            link = heading.find("a") if heading else None
            if link and link.get("href"):
                hits.append((link.get("title"), self.base_url + link.get("href")))
        if not hits:
            raise ValueError(f"no results for '{topic}'")
        return None, hits[:MAX_CANDIDATES]

    def article(self, url):
        response = self.get(url)
        return Article(response.url, BeautifulSoup(response.text, "lxml"))


def clean(tag):
    return " ".join(tag.get_text().split())


def in_noise(tag):
    # is this tag sitting inside a table or one of the NOISE_CLASSES boxes
    if tag.find_parent("table") is not None:
        return True
    for name in NOISE_CLASSES:
        if tag.find_parent(class_=name) is not None:
            return True
    return False


def in_list(tag):
    return tag.find_parent(["ul", "ol"]) is not None


def table_rows(table):
    rows = []
    for row in table.find_all("tr"):
        cells = [clean(cell) for cell in row.find_all(["th", "td"])]
        if cells:
            rows.append(cells)
    return rows


class Article:
    # sections looks like
    #   [{"title": "History", "blocks": [("paragraph", "..."), ("ul", [...]), ...]}, ...]
    # kind = paragraph / h3 / h4 / ul / ol / table

    def __init__(self, url, soup):
        self.url = url
        self.soup = soup
        heading = soup.find("h1")
        self.title = clean(heading) if heading else "Untitled"
        self.sections = []

    def is_disambiguation(self):
        return self.soup.find(class_="dmbox-disambig") is not None

    def parse(self):
        content = self.soup.find("div", id="mw-content-text")
        body = content.find("div", class_="mw-parser-output") if content else None
        if body is None:
            raise ValueError("the page layout looks different from what I expected")

        # get rid of [1], [citation needed], [edit]
        for mark in body.find_all("sup", class_="reference"):
            mark.decompose()
        for mark in body.find_all("sup", class_="noprint"):
            mark.decompose()
        for mark in body.find_all("span", class_="mw-editsection"):
            mark.decompose()
        for br in body.find_all("br"):
            br.replace_with(" ")    # otherwise "New York<br>City" turns into "New YorkCity"

        sections = [{"title": "Introduction", "blocks": []}]
        for tag in body.find_all(["h2", "h3", "h4", "p", "ul", "ol", "table"]):
            blocks = sections[-1]["blocks"]
            if tag.name == "h2":
                sections.append({"title": clean(tag), "blocks": []})
            elif in_noise(tag):
                continue
            elif tag.name in ("h3", "h4"):
                blocks.append((tag.name, clean(tag)))
            elif tag.name == "table":
                if "wikitable" in (tag.get("class") or []):
                    rows = table_rows(tag)
                    if rows:
                        blocks.append(("table", rows))
            elif tag.name == "p":
                text = clean(tag)
                if text:
                    blocks.append(("paragraph", text))
            elif not in_list(tag):    # only top level lists, nested ones came out twice
                items = [clean(li) for li in tag.find_all("li") if li.parent is tag]
                if items:
                    blocks.append((tag.name, items))

        self.sections = []
        for section in sections:
            if section["title"] not in SKIP_TITLES and section["blocks"]:
                self.sections.append(section)
        if not self.sections:
            raise ValueError("this article seems to be empty")

    def default_filename(self):
        name = self.title.strip()
        for char in BAD_FILENAME_CHARS:
            name = name.replace(char, "")
        name = name.replace(" ", "_").strip(".")
        if name == "":
            name = "article"
        return name + ".txt"


def wrap(text, width=WRAP_WIDTH):
    # break a long paragraph into lines of at most width characters
    lines = []
    line = ""
    for word in text.split():
        if line and len(line) + 1 + len(word) > width:
            lines.append(line)
            line = word
        elif line:
            line += " " + word
        else:
            line = word
    if line:
        lines.append(line)
    return lines


def render_table(rows):
    # pad each column to the widest cell (long cells are allowed to stick out)
    widths = []
    for row in rows:
        for i, cell in enumerate(row):
            if i >= len(widths):
                widths.append(0)
            widths[i] = max(widths[i], min(len(cell), MAX_COLUMN))
    lines = []
    for row in rows:
        padded = []
        for i, cell in enumerate(row):
            padded.append(cell.ljust(widths[i]))
        lines.append("  | " + " | ".join(padded) + " |")
    return lines


def render_section(section):
    title = section["title"]
    lines = [title.upper(), "-" * len(title)]
    for kind, content in section["blocks"]:
        if kind == "h3":
            lines.append("")
            lines.append(f"## {content}")
        elif kind == "h4":
            lines.append("")
            lines.append(f"### {content}")
        elif kind == "paragraph":
            lines.extend(wrap(content))
            lines.append("")
        elif kind == "ul":
            lines.extend([f"  - {item}" for item in content])
            lines.append("")
        elif kind == "ol":
            lines.extend([f"  {n}. {item}" for n, item in enumerate(content, start=1)])
            lines.append("")
        elif kind == "table":
            lines.extend(render_table(content))
            lines.append("")
    return "\n".join(lines) + "\n"


def format_txt(article, sections):
    # same text the console app wrote to disk, but returned as a string
    rule = "=" * 60
    header = (f"{rule}\n"
              f"Article: {article.title}\n"
              f"Source: {article.url}\n"
              f"Extracted: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
              f"Text from Wikipedia, CC BY-SA 4.0\n"
              f"{rule}\n\n")
    return "\n".join([header] + [render_section(s) for s in sections])


def block_counts(section):
    counts = {"paragraph": 0, "list": 0, "table": 0, "subheading": 0}
    for kind, _ in section["blocks"]:
        if kind in ("ul", "ol"):
            counts["list"] += 1
        elif kind in ("h3", "h4"):
            counts["subheading"] += 1
        else:
            counts[kind] += 1
    return counts


def numbered_filename(filename, existing):
    # japan.txt -> japan_2.txt, japan_3.txt ... checked against a list of names
    # already downloaded in this session (never against the filesystem)
    if filename not in existing:
        return filename
    stem, dot, ext = filename.rpartition(".")
    if not dot:
        stem, ext = filename, ""
    suffix = "." + ext if dot else ""
    n = 2
    while f"{stem}_{n}{suffix}" in existing:
        n += 1
    return f"{stem}_{n}{suffix}"


def search_topic(wiki, topic):
    # web-friendly wrapper around the console search flow.
    # returns (article, hits, error); exactly one of them is meaningful:
    #   article parsed          -> (Article, [], None)
    #   several candidates      -> (None, [(title, url), ...], None)
    #   anything went wrong     -> (None, [], "readable message")
    try:
        article, hits = wiki.search(topic)
        if article is not None:
            article.parse()
        return article, hits, None
    except ValueError as error:
        return None, [], str(error)
    except (AttributeError, TypeError):
        return None, [], "couldn't parse the page, did Wikipedia change its layout again?"


def load_hit(wiki, url):
    # open one of the candidate pages and parse it. returns (article, error)
    try:
        article = wiki.article(url)
        article.parse()
        return article, None
    except ValueError as error:
        return None, str(error)
    except (AttributeError, TypeError):
        return None, "couldn't parse the page, did Wikipedia change its layout again?"
