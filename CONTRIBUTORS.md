# Contributors and Development Credit

## Project owner / product direction

**Andreas / flamingsnowflake**

Andreas originated the project from a real-world house search and remains the project owner/operator. He defined the practical problem, property-selection goals, hard exclusions, scoring priorities and the acceptance criteria that determine whether a feature is actually useful.

His contribution includes:

- originating the idea and continuously defining what the system should solve;
- supplying real portal examples and edge cases;
- deciding the house/land search policy and scoring priorities;
- validating behavior against real listings in production;
- operating the reference deployment;
- making product decisions when trade-offs were required;
- repeatedly testing changes in the real workflow and reporting where theory did not match reality.

## Architecture and implementation — ChatGPT / OpenAI

The **majority of the software architecture, implementation work, debugging, patch design, regression tests and technical documentation** in the current system was produced collaboratively by **ChatGPT by OpenAI, using GPT-5.6 Sol**, in an iterative conversation with Andreas.

That work includes substantial portions of:

- scoring architecture and `incomplete` semantics;
- condition-aware effective-price scoring;
- geo/noise/water scoring integration;
- Ohne-Makler scoring behavior;
- Telegram commands, property workflows and Labor queues;
- Energy and Condition Labor auto-advance;
- browser/Tampermonkey enrichment architecture;
- canonical Python energy parsing and DOM hint handling;
- explicit portal-condition extraction;
- blacklist and deleted-listing terminal events;
- purge behavior and queue resilience;
- duplicate-refresh preservation rules;
- SQLite consistency/locking fixes;
- regression-test design and debugging procedures;
- Git checkpoint, backup and operational safety workflows;
- system architecture, scoring, browser enrichment, disaster recovery and operations documentation.

A fair shorthand for the development history is:

> **Andreas defined the real problem, priorities and acceptance criteria; ChatGPT performed most of the software engineering required to turn those requirements into the working system; both iterated together against real production behavior.**

The AI assistance is credited for transparency and historical accuracy. ChatGPT/OpenAI is not listed as a legal copyright owner, repository account or human maintainer, and this credit does not imply endorsement by OpenAI.

## Development method

The project was developed unusually close to production reality: a requirement or failure was observed on a real listing, the implementation was inspected and changed, a regression test was added where practical, and the operator immediately validated the result in the actual Telegram/browser workflow.

This feedback loop is an important part of why portal-specific edge cases, incomplete evidence, duplicate alerts and browser-only information are treated explicitly rather than hidden behind a generic score.

## Future contributions

If the project is ever shared with other contributors, changes should preserve the central design values:

- do not turn unknown evidence into fake certainty;
- prefer explainable scoring over opaque ranking;
- protect user privacy and credentials;
- avoid aggressive portal behavior or bypassing access controls;
- add regression tests for portal-specific parsing changes;
- keep operator-specific criteria configurable rather than hardcoding one person's house search;
- preserve a clean path from evidence -> scoring explanation -> human correction.
