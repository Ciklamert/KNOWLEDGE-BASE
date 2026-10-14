# 17 - Requirements writer (Software Requirements Specification)

UI **Requirements**, `POST /api/srs`, MCP `write_requirements`. It writes a Software Requirements Specification (SRS)
in plain language that business people, testers and managers understand, in **your organisation's own format**. Code
paths and document names appear only in an appendix for the technical team.

There is one request field and no mode to choose. The request can be:
- **system requirements** (any length; pasted, or loaded from a Word, PDF or other file) or a **new idea**: they are
  the source of the requirements, and every part of them is covered;
- a **topic of the current system** ("the billing system", "müşteri iadeleri"): the code and documents are then the
  source;
- or a mix of both.

In every case each requirement is checked against the current code and documents: what already exists, what must
change, what is new, which rules apply and which systems are affected.

## 1. Formats: only yours
There is no built-in format. A format is your template as Markdown, kept in `data/srs/templates/`:
- **Its headings are the sections**, written in order: the most used heading level that occurs at least twice (`##`
  in most typed formats, `#` in a converted Word template). Deeper headings stay inside their section as structure to
  follow.
- **The text under a heading says what to write there**, or is example text to replace; fixed text is kept.
- The writer follows the format's numbering, requirement ID style and fields. Write IDs with a question mark
  (`FR-?`, `REQ-?`, `SRS-?`); every prefix is numbered on its own afterwards (`FR-001`, `FR-002`, `REQ-001` …).
- `{{title}}`, `{{date}}`, `{{scope}}` and `{{language}}` are filled in wherever the format uses them.
- The planner decides which sections are written once per capability (feature area), for example the functional
  requirements.

Add a format under **Formats**: *Load from a file* converts your Word or PDF template to Markdown (check it, then
*Save format*), or type it. *Open selected* edits a saved format; *Delete* removes it. Writing needs at least one
saved format; without one the writer says how to add it.

Example of a small typed format:
```markdown
# Yazılım Gereksinimleri - {{title}}
| Tarih | {{date}} |

## 1. Amaç
Sistemin amacı ve kapsamı, iş diliyle.

## 2. İşlevsel gereksinimler
Her yetenek için REQ-? maddeleri: "Sistem ... -malıdır" biçiminde, kabul kriterleriyle.

## 3. Sözlük
Terim | Anlam tablosu.
```

## 2. Using it
1. Paste the system requirements, describe the new idea, or name a topic of the current system; or *Load from a file*
   (any supported document, converted to Markdown).
2. Choose the **Scope** (one repository, or a set: every repository of the set is examined), the **Format**, the
   **Language** (*Same as the request*, English, Turkish; the API accepts any language name) and the **Model**.
3. Press **Write specification**. The job shows every step: evidence, plan, each capability, each section.
4. Read the result, then **Copy Markdown**, **Download .md**, or **Add to document graph** so that search, ask and
   enhance can use it. Every specification is listed under *Written specifications* and kept in
   `data/srs/output/` with a `.json` file of metadata (title, request, scope, format, language, model,
   capabilities, errors, model calls and tokens, duration).

## 3. How a specification is written
1. **Evidence**: a search for the request with model query expansion ([05](05-SEARCH-ASK-ENHANCE.md) §3), an
   architecture overview of every repository in scope (at most 8), and the document passages and concepts.
2. **Plan**: one model call lists the system name, a short summary, the capabilities (feature areas in business
   words, at most `BRAIN_SRS_MAX_CAPABILITIES`, each with search queries), the format sections to write once per
   capability, and glossary candidates, as JSON. For system requirements or a new idea the capabilities come from the
   request (every part of it must belong to one); for a topic they come from the evidence. Each records the part of
   the request it comes from. Without a plan the request itself is the only capability.
3. **Each capability**: a targeted search with the capability's queries, then a grounded writing call that may use
   the AI-BRAIN tools for up to 3 rounds, following the guidance of the per-capability sections and the part of the
   request.
4. **Each other section**: one call with the section's guidance, the plan, the capability texts, the glossary
   candidates and the request, so the document stays consistent.
5. **Assembly**: placeholders filled; requirement IDs numbered per prefix; the appendix lists, per capability, the
   code and documents the requirements were checked against.

The whole run is bounded by `BRAIN_SRS_TIMEOUT`. When less than a minute is left, remaining capabilities are skipped;
when less than 30 seconds are left, remaining sections are marked "not written"; both are reported in `errors`.

## 4. Writing rules given to the model
- Follow the format exactly: sections, headings, numbering, ID style, fields and conventions.
- Plain language: no class, function, file, table, endpoint or library names, programming languages or frameworks
  in the body; technical facts are translated into business behaviour.
- One testable "shall" statement per requirement, unless the format prescribes another sentence style.
- ISO/IEC/IEEE 29148 quality: necessary, unambiguous (no "fast", "user-friendly", "etc."), complete, singular,
  feasible, verifiable, consistent.
- A status per requirement, in the format's status field or as "(Status: …)": *Implemented*, *Partly
  implemented*, *Changes existing behaviour*, *New*, *Documented only* (in documents, not in code) or *Implemented,
  not documented*.
- Facts about the current system only from the evidence: nothing invented; unknowns go to the open issues; conflicts
  between code and documents reported.
- Behaviour the request asks for but leaves open is proposed and marked "to be confirmed"; new behaviour is never
  claimed to exist.

## 5. Settings and cost
`BRAIN_SRS_MODEL`, `BRAIN_SRS_TIMEOUT` (total, default 1800 s), `BRAIN_SRS_MAX_CAPABILITIES` (12),
`BRAIN_SRS_MAX_TOKENS` (per section, 3000), `BRAIN_SRS_TEMPERATURE` (0.2), `BRAIN_SRS_LANGUAGE` (default language,
`auto` = the request's language: Turkish for a Turkish request, otherwise English).

Cost: about 2 + capabilities + sections model calls plus tool rounds; 8 capabilities with a 10-section format is
about 20-30 calls.
