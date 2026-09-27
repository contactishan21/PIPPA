from __future__ import annotations

import math
import re
import hashlib
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime, date


TOKEN_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*", re.I)
CLAUSE_RE = re.compile(r"^###\s+([A-Z][A-Z0-9]{1,3}-\d{3}-\d+\.\d+)\s*$")
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "can", "do",
    "does", "for", "from", "had", "has", "have", "how", "i", "if", "in", "into",
    "is", "it", "may", "my", "of", "on", "or", "our", "should", "that", "the",
    "their", "this", "to", "was", "we", "what", "when", "where", "which", "who",
    "with", "would", "you", "your",
}

SYNONYMS = {
    "return": {"refund", "exchange", "defective", "receipt", "credit", "replacement"},
    "refund": {"return", "credit", "repayment", "customer"},
    "defective": {"damage", "damaged", "faulty", "inspection", "return"},
    "vendor": {"supplier", "procurement", "invoice", "contract"},
    "supplier": {"vendor", "procurement", "invoice", "rtv"},
    "invoice": {"vendor", "supplier", "payment", "late", "receipt"},
    "delivery": {"logistics", "fleet", "carrier", "route", "customer"},
    "fleet": {"transport", "carrier", "delivery", "vehicle", "emergency"},
    "cash": {"till", "petty", "advance", "shortage", "variance"},
    "gift": {"hospitality", "vendor", "ethics", "conflict"},
    "meal": {"hospitality", "vendor", "gift", "ethics"},
    "danger": {"evacuation", "safety", "emergency", "security"},
    "price": {"mismatch", "promotion", "label", "shelf"},
    "collect": {"collection", "pickup", "identity", "order"},
}


def corpus_revision(knowledge_dir: Path) -> str:
    """Fingerprint all controlled corpus bytes so cached evidence cannot go stale."""
    digest = hashlib.sha256()
    manifest = knowledge_dir.parent / "manifest.json"
    candidates = ([manifest] if manifest.is_file() else []) + sorted(
        path for path in knowledge_dir.glob("*.md") if path.is_file()
    )
    for path in candidates:
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def tokenize(text: str) -> list[str]:
    tokens = [t.lower() for t in TOKEN_RE.findall(text) if t.lower() not in STOPWORDS]
    expanded = list(tokens)
    for token in tokens:
        expanded.extend(SYNONYMS.get(token, ()))
        if token.endswith("s") and len(token) > 4:
            expanded.append(token[:-1])
    return expanded


@dataclass
class PolicyDocument:
    document_id: str
    title: str
    function: str
    owner: str
    status: str
    version: str
    effective_date: str
    audience: str = ""
    scenario: str = ""
    search_terms: str = ""
    clauses: list[tuple[str, str]] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    approvals: list[str] = field(default_factory=list)
    records: list[str] = field(default_factory=list)
    donts: list[str] = field(default_factory=list)
    retrieval_eligible: bool = False
    escalation: str = ""
    related: str = ""


@dataclass(frozen=True)
class Passage:
    document_id: str
    title: str
    function: str
    owner: str
    version: str
    effective_date: str
    clause_id: str
    text: str
    context: str


@dataclass(frozen=True)
class SearchHit:
    passage: Passage
    score: float


def _frontmatter(lines: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    if not lines or lines[0].strip() != "---":
        return result
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            key, value = line.split(":", 1)
            result[key.strip()] = value.strip()
    return result


def _section(lines: list[str], heading: str) -> list[str]:
    marker = f"## {heading}"
    try:
        start = lines.index(marker) + 1
    except ValueError:
        return []
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("## ")), len(lines))
    return lines[start:end]


def _bullets(lines: list[str]) -> list[str]:
    return [re.sub(r"^(?:- |\d+\.\s+)", "", line).strip() for line in lines if re.match(r"^(?:- |\d+\.\s+)", line)]


def _control_value(lines: list[str], label: str) -> str:
    pattern = re.compile(rf"^-\s+\*\*{re.escape(label)}:\*\*\s*(.+)$", re.I)
    return next((match.group(1).strip() for line in lines if (match := pattern.match(line.strip()))), "")


def parse_policy(path: Path) -> PolicyDocument:
    lines = path.read_text(encoding="utf-8").splitlines()
    meta = _frontmatter(lines)
    control_lines = _section(lines, "Control information")
    document = PolicyDocument(
        document_id=meta.get("document_id", path.stem.split("_")[0]),
        title=meta.get("title", path.stem),
        function=meta.get("function", ""),
        owner=meta.get("owner", ""),
        status=meta.get("status", ""),
        version=meta.get("version", ""),
        effective_date=meta.get("effective_date", ""),
        audience=_control_value(control_lines, "Audience"),
        retrieval_eligible=meta.get("retrieval_eligible", "").lower() == "true",
    )
    use_lines = _section(lines, "When to use this document")
    document.scenario = " ".join(line.strip() for line in use_lines if line.strip())
    search_lines = _section(lines, "Search terms")
    document.search_terms = " ".join(line.strip().lstrip("- ") for line in search_lines if line.strip())
    document.steps = _bullets(_section(lines, "Procedure"))
    document.approvals = _bullets(_section(lines, "Approval and decision authority"))
    document.records = _bullets(_section(lines, "Required records"))
    document.donts = _bullets(_section(lines, "Do not"))
    document.escalation = " ".join(_section(lines, "Escalation rule")).strip()
    document.related = " ".join(_section(lines, "Related controlled documents")).strip()
    for index, line in enumerate(lines):
        match = CLAUSE_RE.match(line)
        if not match:
            continue
        quote_lines: list[str] = []
        for following in lines[index + 1 :]:
            if following.startswith("### ") or following.startswith("## "):
                break
            if following.startswith("> "):
                quote_lines.append(following[2:].strip())
        if quote_lines:
            document.clauses.append((match.group(1), " ".join(quote_lines)))
    return document


class KnowledgeBase:
    def __init__(self, directory: Path):
        self.documents = [parse_policy(path) for path in sorted(directory.glob("*.md"))]
        def eligible(doc):
            for fmt in ("%d %B %Y", "%Y-%m-%d"):
                try:
                    effective = datetime.strptime(doc.effective_date, fmt).date()
                    return doc.status == "CURRENT" and doc.retrieval_eligible and effective <= date.today()
                except ValueError:
                    continue
            return False
        self.documents = [doc for doc in self.documents if eligible(doc)]
        self.passages: list[Passage] = []
        for doc in self.documents:
            context = " ".join([doc.title, doc.function, doc.audience, doc.scenario, *doc.steps, *doc.approvals, *doc.donts])
            for clause_id, text in doc.clauses:
                self.passages.append(Passage(
                    document_id=doc.document_id, title=doc.title, function=doc.function,
                    owner=doc.owner, version=doc.version, effective_date=doc.effective_date,
                    clause_id=clause_id, text=text, context=context,
                ))
        self._tokens = [tokenize(f"{p.clause_id} {p.document_id} {p.title} {p.text} {p.context}") for p in self.passages]
        self._doc_freq = Counter(token for tokens in self._tokens for token in set(tokens))
        self._average_length = sum(map(len, self._tokens)) / max(len(self._tokens), 1)
        self._scope_text = {
            doc.document_id: " ".join((doc.title, doc.audience, doc.scenario, doc.search_terms))
            for doc in self.documents
        }

    @property
    def functions(self) -> list[str]:
        return sorted({doc.function for doc in self.documents if doc.function})

    def search(self, query: str, limit: int = 5, functions: set[str] | None = None) -> list[SearchHit]:
        query_counts = Counter(tokenize(query))
        scores: list[SearchHit] = []
        corpus_size = max(len(self.passages), 1)
        for passage, tokens in zip(self.passages, self._tokens):
            if functions and passage.function not in functions:
                continue
            frequencies = Counter(tokens)
            score = 0.0
            for token, query_weight in query_counts.items():
                if token not in frequencies:
                    continue
                document_frequency = self._doc_freq[token]
                idf = math.log(1 + (corpus_size - document_frequency + 0.5) / (document_frequency + 0.5))
                tf = frequencies[token]
                norm = tf + 1.5 * (0.25 + 0.75 * len(tokens) / self._average_length)
                score += idf * (tf * 2.5 / norm) * min(query_weight, 2)
            if passage.clause_id.lower() in query.lower() or passage.document_id.lower() in query.lower():
                score += 12
            if score > 0:
                scores.append(SearchHit(passage=passage, score=round(score, 3)))
        scores.sort(key=lambda hit: (-hit.score, hit.passage.clause_id))
        # First reserve one result per relevant document. This prevents a long
        # policy from occupying every slot and hiding a linked controlling policy.
        selected: list[SearchHit] = []
        seen_documents: set[str] = set()
        for hit in scores:
            if hit.passage.document_id not in seen_documents:
                selected.append(hit)
                seen_documents.add(hit.passage.document_id)
            if len(selected) >= min(3, limit):
                break
        for hit in scores:
            if hit not in selected:
                selected.append(hit)
            if len(selected) >= limit:
                break
        return selected

    def document_for(self, document_id: str) -> PolicyDocument | None:
        return next((doc for doc in self.documents if doc.document_id == document_id), None)

    def passage_for(self, clause_id: str) -> Passage | None:
        return next((passage for passage in self.passages if passage.clause_id == clause_id), None)

    def scope_matches(self, query: str, functions: set[str] | None = None) -> list[str]:
        """Return policies whose declared scope materially matches the request.

        This deliberately ignores procedure and clause boilerplate. A document
        mentioning a word incidentally must not become authority for a request
        outside its title, stated use case or maintained search terms.
        """
        generic = {
            "policy", "policies", "procedure", "procedures", "process", "processes",
            "help", "guidance", "guide", "question", "issue", "problem", "situation",
            "employee", "employees", "company", "business", "manager", "team", "work",
            "need", "want", "know", "tell", "check", "please", "normal", "standard",
            "approve", "approval", "approved", "authority", "allowed", "apply",
            "vendor", "vendors", "supplier", "suppliers", "customer", "customers",
            "store", "stores", "item", "items", "aed", "day", "days", "month", "months",
        }
        equivalents = {
            "onboard": {"onboarding"},
            "onboarding": {"onboard"},
            "operate": {"operation", "operating"},
            "operation": {"operate", "operating"},
            "pay": {"payment"},
            "payment": {"pay"},
            "deliver": {"delivery"},
            "delivery": {"deliver"},
            "collect": {"collection", "pickup"},
            "collection": {"collect", "pickup"},
            "buy": {"purchase"},
            "purchase": {"buy"},
            "financial": {"spending", "approval"},
            "spending": {"financial"},
            # Common employee wording for controlled scope terms. These are
            # deliberately limited to maintained policy concepts rather than
            # broad stemming, which could make neighbouring policies match.
            "engage": {"onboarding", "activation"},
            "engaging": {"onboarding", "activation"},
            "limit": {"threshold", "thresholds"},
            "limits": {"threshold", "thresholds"},
            "boundary": {"threshold", "thresholds"},
            "exactly": {"including", "inclusive"},
        }

        scope_text_by_document = getattr(self, "_scope_text", None)
        if scope_text_by_document is None:
            # Supports a safe Streamlit hot reload when an older cached
            # KnowledgeBase instance predates the scope index.
            scope_text_by_document = {
                doc.document_id: " ".join(
                    (doc.title, getattr(doc, "audience", ""), doc.scenario, getattr(doc, "search_terms", ""))
                )
                for doc in self.documents
            }
            self._scope_text = scope_text_by_document

        raw_tokens = {token.lower() for token in TOKEN_RE.findall(query)}
        # A user may write "sick-leave" while policy search terms use
        # "sick leave". Keep the compound but also expose its components for
        # declared-scope matching.
        raw_tokens.update(part for token in tuple(raw_tokens) for part in token.split("-") if part)
        # Keep known compound plural forms aligned with singular policy scope
        # terms (for example, "stocktakes" with the OPS-013 title "stocktake")
        # without turning ordinary words such as "applies" into false anchors.
        if "stocktakes" in raw_tokens:
            raw_tokens.add("stocktake")
            raw_tokens.discard("stocktakes")
        raw_query = raw_tokens - STOPWORDS
        anchors = {token for token in raw_query if token not in generic and not token.isdigit()}
        expanded_anchors = set(anchors)
        for token in anchors:
            expanded_anchors.update(equivalents.get(token, set()))

        if not anchors:
            return []

        matches: list[tuple[int, float, str]] = []
        for doc in self.documents:
            if functions and doc.function not in functions:
                continue
            scope_tokens = {token.lower() for token in TOKEN_RE.findall(scope_text_by_document[doc.document_id])}
            title_tokens = {token.lower() for token in TOKEN_RE.findall(doc.title)}
            overlap = expanded_anchors & scope_tokens
            title_overlap = expanded_anchors & title_tokens
            coverage = len(overlap) / max(len(anchors), 1)
            if len(title_overlap) >= 2 or len(overlap) >= 2 or coverage >= 0.5:
                matches.append((len(title_overlap), coverage, doc.document_id))
        # Boundary questions about an AED limit are governed by the explicit
        # financial-threshold definition, even when the wording contains no
        # policy title terms (for example, “up to” versus “exactly”).
        if (
            re.search(r"\b(limit|threshold|boundary)\b", query, re.I)
            and re.search(r"\bup\s+to\b", query, re.I)
            and re.search(r"\b(exactly|including|inclusive)\b", query, re.I)
            and re.search(r"\bAED\b", query, re.I)
            and any(doc.document_id == "GOV-001" for doc in self.documents)
            and not any(document_id == "GOV-001" for _, _, document_id in matches)
        ):
            matches.append((3, 1.0, "GOV-001"))
        # An explicit approval question containing an AED amount belongs to the
        # master financial authority matrix even when the user omits words such
        # as "commitment" or "spending".
        if (
            re.search(r"\b(approv\w*|authority|sign\w*)\b", query, re.I)
            and re.search(r"\bAED\b", query, re.I)
            and any(doc.document_id == "FIN-001" for doc in self.documents)
            and not any(document_id == "FIN-001" for _, _, document_id in matches)
        ):
            matches.append((3, 1.0, "FIN-001"))
        # A customer's damaged or faulty item belongs to the controlled defect
        # inspection path even when they use ordinary words such as "broken"
        # and "replacement" rather than the policy title.
        if (
            re.search(r"\b(customer|shopper|purchaser|bought|purchase)\b", query, re.I)
            and re.search(r"\b(damag\w*|defect\w*|faulty|broken|not working)\b", query, re.I)
            and re.search(r"\b(return|exchange|replace\w*|refund|credit note|bring\w* (?:in|back))\b", query, re.I)
            and any(doc.document_id == "RET-002" for doc in self.documents)
            and not any(document_id == "RET-002" for _, _, document_id in matches)
        ):
            matches.append((3, 1.0, "RET-002"))
        # Eligibility wording should resolve to the maintained uniform policy;
        # words such as "certain team members" are audience qualifiers, not a
        # separate subject that should make scope matching fail.
        if (
            re.search(r"\b(uniform|uniforms|clothing allowance)\b", query, re.I)
            and re.search(r"\b(who|which|eligible|eligibility|apply|applies|applicable|certain|team members?|employees?|staff|frontline|store[- ]based)\b", query, re.I)
            and any(doc.document_id == "HR-003" for doc in self.documents)
            and not any(document_id == "HR-003" for _, _, document_id in matches)
        ):
            matches.append((3, 1.0, "HR-003"))
        matches.sort(key=lambda item: (-item[0], -item[1], item[2]))
        return [document_id for _, _, document_id in matches]
