# bookfetch

Agent-friendly ebook finder CLI. Tell it a book, it routes the query to a
source that actually works — Chinese classics go to ctext.org (free,
punctuated, mainland-China friendly) before anywhere else.

```
bookfetch search 渊海子平     # JSON results across sources
bookfetch get ctext 296619   # download to ./296619.txt
```

Runtime dependencies: none (Python stdlib only). Python >= 3.10.

See docs/PRD.md for scope and design. MIT licensed.
