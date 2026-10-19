# Request Format

`notesctl.py create` accepts a JSON request file. The Skill creates this file after interpreting the user's request and generating structured drafts.

## Single note

```json
{
  "request_id": "conversation-2026-10-02-spi-dma-01",
  "mode": "single",
  "count": 1,
  "action": "create",
  "publish": true,
  "sources": [
    {"type": "conversation", "description": "当前对话"}
  ],
  "drafts": [
    {"path": "drafts/spi-dma.json"}
  ]
}
```

The draft file contains the generated content:

```json
{
  "title": "SPI DMA 工作原理",
  "slug": "spi-dma",
  "description": "说明 SPI 与 DMA 的数据传输关系。",
  "summary": "说明 SPI 与 DMA 的数据传输关系。",
  "tags": ["embedded", "spi", "dma"],
  "categories": ["嵌入式"],
  "series": ["EmbeddedStudy"],
  "body": "## 工作原理\n\n...",
  "sources": [
    {"type": "conversation", "description": "当前对话"}
  ]
}
```

The deterministic renderer adds `date`, `lastmod`, `draft`, and `note_id`. The model must not choose an output path for a new note.

## Batch

```json
{
  "request_id": "conversation-2026-10-02-dma-series-01",
  "mode": "batch",
  "count": 3,
  "action": "create",
  "topics": ["SPI DMA", "UART DMA", "DMA 环形缓冲区"],
  "drafts": [
    {"path": "drafts/01-spi.json"},
    {"path": "drafts/02-uart.json"},
    {"path": "drafts/03-ring-buffer.json"}
  ]
}
```

`single` requires exactly one draft and `count: 1`. `batch` requires `count` drafts. The validator rejects a mismatch before any content file is written.

## Updating an existing note

Use `action: "update"` and put either an existing `note_id` or an explicit relative content path in each draft entry. Do not infer an update from a similar title.
