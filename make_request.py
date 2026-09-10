"""Build an HTTP request file from a local PDF/TXT and approved catalogue."""
import argparse
import base64
import json
from pathlib import Path

from local_api import MAX_REQUEST_BYTES


def make_request(rfq, catalogue):
    if rfq.suffix.lower() not in ('.txt', '.pdf'):
        raise ValueError('RFQ must be TXT or PDF')
    if rfq.stat().st_size > MAX_REQUEST_BYTES or catalogue.stat().st_size > MAX_REQUEST_BYTES:
        raise ValueError('input exceeds the local HTTP demo limit')
    pdf = rfq.suffix.lower() == '.pdf'
    request = {
        'rfq': {
            'format': 'pdf_base64' if pdf else 'txt',
            'content': base64.b64encode(rfq.read_bytes()).decode('ascii') if pdf else rfq.read_text(encoding='utf-8-sig'),
        },
        'catalogue_csv': catalogue.read_text(encoding='utf-8-sig'),
    }
    body = json.dumps(request, ensure_ascii=True).encode('utf-8')
    if len(body) > MAX_REQUEST_BYTES:
        raise ValueError('encoded HTTP JSON exceeds 1 MB; use a smaller sample')
    return body


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('rfq', type=Path)
    parser.add_argument('catalogue', type=Path)
    parser.add_argument('--out', type=Path, default=Path('request.json'))
    args = parser.parse_args()
    try:
        body = make_request(args.rfq, args.catalogue)
        args.out.write_bytes(body)
    except (ValueError, OSError) as exc:
        parser.exit(1, f'Error: {exc}\n')
    print(f'Created {args.out.name}: {len(body)} bytes; no request sent.')


if __name__ == '__main__':
    main()
