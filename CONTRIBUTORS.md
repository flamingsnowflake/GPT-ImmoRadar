# Contributors and Development Credit

## Project owner / product direction

**Andreas / flamingsnowflake**

- originated the project from a real-world house search;
- defined the property-selection goals, hard exclusions and scoring priorities;
- provided portal examples and production feedback;
- validated behavior against real listings;
- operates the reference deployment and made the calls where product trade-offs were required.

## AI-assisted development

A substantial part of the architecture, implementation support, debugging, regression testing and project documentation was developed collaboratively with **ChatGPT by OpenAI, using GPT-5.6 Sol**.

This includes work on areas such as:

- modular scoring/incomplete-state semantics;
- Telegram Labor workflows and auto-advance;
- browser/Tampermonkey enrichment architecture;
- energy and explicit-condition parsing;
- terminal-event/purge handling;
- duplicate-refresh resilience;
- regression-test design;
- Git/backup/operational safety workflows;
- documentation and public-release planning.

The AI assistance is credited for transparency and historical accuracy. It is not listed as a legal copyright owner or maintainer account.

## Contributions

If the project is published publicly, contributions are welcome when they preserve the central design values:

- do not turn unknown evidence into fake certainty;
- prefer explainable scoring over opaque ranking;
- protect user privacy and credentials;
- avoid aggressive portal behavior/bypassing access controls;
- add regression tests for portal-specific parsing changes;
- keep operator-specific criteria configurable rather than hardcoding one person's house search.
