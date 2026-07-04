import json, gc, sys
from pathlib import Path
from extractor import extract_page
from chunker import chunk_markdown

raw_dir = Path('output/raw_html')
kb_path = Path('output/knowledge_base.jsonl')

files = []
for html_path in sorted(raw_dir.glob('*.html')):
    meta_path = raw_dir / f'{html_path.stem}.meta.json'
    if not meta_path.exists():
        continue
    if html_path.stat().st_size > 400_000:
        print(f'[skip-large] {html_path.name}', flush=True)
        continue
    files.append(html_path)

print(f'Total files to process: {len(files)}', flush=True)

total = 0
with open(kb_path, 'w', encoding='utf-8') as kb:
    for i, html_path in enumerate(files):
        meta_path = raw_dir / f'{html_path.stem}.meta.json'
        meta = json.loads(meta_path.read_text())
        url = meta.get('url', '')
        try:
            html = html_path.read_text(encoding='utf-8', errors='ignore')
            page = extract_page(html, url)
            del html
            gc.collect()
        except Exception as e:
            print(f'[error] {html_path.name}: {e}', flush=True)
            continue

        if page.markdown and len(page.markdown.strip()) >= 30:
            chunks = chunk_markdown(
                page.markdown, page.url, page.title,
                page.category, meta.get('fetched_at', '')
            )
            for chunk in chunks:
                record = {
                    'id': chunk.id, 'type': 'text',
                    'content': chunk.content, 'category': chunk.category,
                    'source_url': chunk.source_url, 'page_title': chunk.page_title,
                    'image_path': None, 'scraped_at': chunk.scraped_at,
                }
                kb.write(json.dumps(record, ensure_ascii=False) + '\n')
                total += 1

        del page
        gc.collect()

        if (i + 1) % 25 == 0:
            print(f'[progress] {i+1}/{len(files)} pages | {total} records', flush=True)
            kb.flush()

print(f'[done] {total} total records written', flush=True)
