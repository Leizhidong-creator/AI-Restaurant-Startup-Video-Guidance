# README Redesign Specification

## Objective

Redesign the public README for 口袋参谋 / PocketMentor as a branded product narrative, technical dossier, and reproducible project guide. The README must explain the product deeply enough that a reader understands the user problem, the end-to-end product loop, the knowledge and evidence model, the real-time video path, the author's engineering contributions, the project's social value, and its limitations.

## Final Scope Addendum (2026-09-02)

- Remove the entire `工程评估` section and its 142-test table from the README. Test commands remain in local setup for reproducibility.
- Rename `当前到底用了什么` to `项目设计`. Keep the existing explanations of SQLite, lexical retrieval, RAG, and Retrieval Port; do not rewrite those concepts for a general audience in the README.
- Add an official-logo collaboration masthead above the hero: 太原理工大学 × 上海交通大学 × 浙江大学, followed by `三校联合创作`.
- Use only official public logo assets sourced from each university's official website, with source URLs recorded in the README asset notes.

## Central Narrative

The README has one central thesis:

> 把过去昂贵、稀缺、低频的专家到店诊断，转化为普通创业者随时可以从手机发起的视频诊断体验。

The hero copy is:

- Product: `口袋餐谋 / PocketMentor`
- Headline: `把餐饮专家装进口袋`
- Supporting statement: `让刷到的爆店视频不止被看见：解构它为什么成功，对照你自己的门店，再把经验转化为可以执行和验证的改造方案。`

The README must not claim that AI replaces licensed experts or guarantees business success. "手机里的餐饮专家" is a product metaphor for making an expert-style diagnostic process accessible.

## Audience

Primary readers are competition judges, recruiters, AI application engineers, product builders, and potential collaborators. Chinese is the primary language. English is retained for the product name, architecture terms, and code identifiers where it improves precision.

## Visual Direction

The aesthetic is a playful restaurant field guide with research-grade technical discipline:

- 75% professional and 25% playful.
- Core colors: ink black and jade green.
- Accent colors: tomato red and mustard yellow.
- Base surface: clean paper white.
- The brand character acts as a guide, not as decoration that competes with the technical content.
- Playful motifs are route markers, evidence stamps, observation labels, menu/checklist references, and comparison annotations.
- The README body remains restrained and scannable.

The existing `web/assets/pocket-bro-cutout.png` must not be reused in the README because it contains visible generation-platform watermarks. A new original, watermark-free hero asset must be created.

## Information Architecture

1. **Hero**: brand visual, product name, headline, supporting statement, competition recognition, and direct navigation.
2. **Abstract**: one concise paragraph explaining the expert-service and short-video-value transformations.
3. **Product loop**: from a viral restaurant video to a validated store transformation plan.
4. **Problem framing**: why copying successful stores, generic chat, static forms, and traditional consultation are insufficient.
5. **Method overview**: `Knowledge Base + Skill + Evidence Runtime` and the two-store comparison model.
6. **Video pipeline**: upload/link ingestion, validation, resolver fallback, SHA-256 reuse, model analysis, timestamped evidence, private knowledge ingestion, case deconstruction, and live capture.
7. **Real-time diagnosis**: browser media, WebRTC/Qwen Realtime session, six-shot guidance, tool execution, event persistence, and report generation.
8. **Knowledge system**: platform and private knowledge, data schema, evidence grades, retrieval policy, stable evidence IDs, and privacy boundaries.
9. **Skill workflow**: stage classification, deterministic safety gates, highest-value next action, tool orchestration, evidence threshold, judgment validation, and final output contract.
10. **Engineering decisions**: problem, decision, implementation, effect, and remaining boundary for each major challenge described in the portfolio document.
11. **Technology access and social value**: service accessibility, contextual diagnosis, evidence literacy, and transformation of short videos from passive content into reusable case material.
12. **Evaluation**: explain what the 51 decision-core, 77 backend, and 14 integration tests cover. Never present these tests as diagnostic accuracy.
13. **Limitations and responsible use**: no success guarantee, POI is not traffic, historical cases do not prove current outcomes, evidence gaps weaken conclusions, browser camera constraints, temporary-storage constraints, and content licensing.
14. **Quick start and repository guide**: installation, configuration, tests, security, and project structure.

## Required Diagrams

All structural diagrams use Mermaid as the version-controlled source of truth and must render natively on GitHub.

1. **Value transformation flowchart**: watched video -> structured case -> user-store observation -> aligned comparison -> transformation plan.
2. **Two-store comparison diagram**: successful-store mechanism map and user-store condition map converge into a dimension-aligned gap diagnosis.
3. **Video and knowledge pipeline flowchart**: ingestion through evidence and private knowledge storage.
4. **Real-time diagnosis sequence diagram**: user, H5, realtime model, backend, Skill, deterministic tools, and report.
5. **Skill and Evidence Runtime state flow**: stage, safety gate, ask/capture/tool loop, evidence threshold, insufficient evidence or validated judgment.

Each diagram must include accessibility metadata when supported, use theme-neutral colors, avoid initialization directives, and avoid inline styles.

## Evidence And Metrics Policy

Metrics must appear only where their meaning is explained:

- `93` platform knowledge records are 52 transferable method cards and 41 cases.
- Evidence grades are 52 reviewed, 25 golden, and 16 secondary records; secondary evidence is not decisive.
- `142` automated tests are 51 decision-core tests, 77 backend tests, and 14 integration tests verified for the sanitized release snapshot.
- Approximately `2 FPS` is a live-video transmission strategy balancing visual observation and transmission cost.
- Approximately `5.8 ms` is a development-environment cache-hit observation, not a general benchmark.
- `48 hours` is the lifetime of the development temporary-upload resource, not production object-storage durability.

The phrase `武汉大区前 10` must not appear. Competition recognition may be stated as `2026 抖音 AI 创变者黑客松武汉大区赛优秀作品`.

## Engineering Contribution Narrative

The README must connect each problem to the author's work:

- Non-transferable success cases -> `Knowledge Base + Skill + Evidence Runtime`.
- Model inference presented as fact -> four-level evidence model and judgment validation.
- Static forms cannot capture a store -> real-time video and guided six-shot capture.
- Unstable model tool calling -> deterministic server-side tool injection and typed results.
- Repeated video-analysis cost -> SHA-256 analysis and same-category deconstruction reuse.
- Large-video constraints -> inline small-video path plus temporary large-video upload.
- Generic retrieval and privacy risk -> platform/private separation, stable evidence IDs, and authenticated user/store scope.

## Honesty And Scope

The README must distinguish:

- Implemented behavior in the public snapshot.
- Development fallbacks and measured observations.
- Recommended production integrations.
- Known limitations and unavailable evidence.

Outdated internal documents must not be used as the source of current counts. The current knowledge manifest and executable code take precedence.

## Acceptance Criteria

- A new reader can explain the complete user journey without reading source code.
- A technical reader can trace each major product claim to a named component or documented boundary.
- The 93 knowledge records and 142 tests are meaningful rather than decorative statistics.
- The author's contribution is explicit without erasing the project's collaborative origin.
- The hero and screenshots contain no visible third-party generation watermark.
- All Mermaid diagrams render on GitHub and remain readable in light and dark themes.
- Local setup commands remain accurate for Windows and Unix-like environments.
- The README contains no secret, private endpoint, personal data, or unsupported performance claim.
