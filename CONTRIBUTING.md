# Contributing to ALL about RSS

Thanks for helping keep this list useful.

One thing first: this repository is **not an Awesome list**. As the README puts it, *"Any service/tool that functions well and is maintained well can be listed here."* That is the whole bar — working and maintained, not prestigious. Three consequences follow:

- **Duplicates are welcome.** Two tools that do the same thing are two options for a reader to choose from.
- **One pull request may contain several entries.** No need to split them.
- **Cross-listing is fine.** If something genuinely belongs in more than one section, list it in each.

## What an entry needs

1. **Relevance.** It is part of the RSS ecosystem — it produces feeds, consumes feeds, converts them, validates them, or helps people work with them.
2. **Alive.** The link resolves, and it is not a parked domain, a "domain for sale" page, or a redirect to something unrelated.
3. **Verifiable feed capability.** It imports or generates RSS feeds, or it is a collection of feeds. Point to where that can be checked: a feed URL, an OPML import doc, or the page of the feature. If the item does not touch feeds at all, explain why it still belongs here.
4. **Maintained.** It works today. Abandoned projects are not added; when an existing one dies, it is struck through rather than deleted.

Not accepted: marketing landing pages with no product behind them, URL shorteners or redirect hops standing in for the real link, and entries unrelated to feeds.

## A single feed is not an entry

This list indexes feeds and the tools around them. It does not index individual publications — one site's feed belongs in your reader, not in this repository. Entries under *Feed Resources / Providers / Recommendations* must therefore be one of:

- **a collection** — a directory, a curated list, a repository of feeds
- **an OPML file** — a bundle of feeds in a single file
- **an aggregator** — one feed that itself merges several sources

A plain "here is my blog's RSS" submission is declined. This is the reason PR #146 was closed, and the existing entries in that section — a web-dev feed collection, an OPML file, a dev directory — show the shape expected.

## Format

An entry is a single Markdown list item under a `##` or `###` section. The smallest valid form:

```markdown
- [Name](https://example.com)
```

With a reference to the [@AboutRSS](https://t.me/s/aboutrss) channel post — optional, add it only if such a post actually exists:

```markdown
- [Feedspot API](https://www.feedspot.com/fs/apireadme) <sup>[290](https://t.me/s/aboutrss/290)</sup>
```

With a short description and icons:

```markdown
- [SearQ](https://searq.org/): a RESTful API that simplifies the search for data from RSS feeds. <sup>[1308](https://t.me/s/aboutrss/1308)</sup> [![Open-Source Software][oss icon]](https://github.com/davidesantangelo/searq.org)![Freeware][freeware icon]
```

What the examples imply:

- **Append to the end of the section.** The list is explicitly unordered. Do not sort, do not insert in the middle.
- **Icons are optional and must be true.** Add one only if the thing really is open source, really is free, really runs on that platform — and link it to the right place. The full legend sits near the top of the README.
- **Match the neighbours.** Spacing before `:`, capitalisation of the description, trailing period — copy the surrounding entries rather than a style guide. Sections differ from each other, and that is accepted.
- **Sub-entries use two-space indent**, as in the `Reeder` entry under *RSS Readers*.

## Picking a section

Choose from the table of contents the section that matches what the thing *does*, not what it is called. If nothing fits, say so in the PR and suggest where you think it belongs — adding a section is possible.

## Disclosure

If you are the author, an employee, an investor, or otherwise commercially involved with what you are submitting, say so in the PR. **Disclosure does not count against you — it is the opposite.** Undisclosed self-promotion is what gets a PR sent back.

## Review

Every PR gets a human read; nothing is auto-merged. That has a direct consequence: review is slow. This repository is maintained by one person in their spare time, so **a response can take weeks**. Silence is not a rejection, and it is not a signal to resubmit.

If a PR has been quiet for a couple of weeks, one comment is fine. Repeated pings will not move it up the queue.

You may be asked for a feed URL, a maintenance signal, or a note on where the entry sits relative to its neighbours. You will get a clear answer either way.
