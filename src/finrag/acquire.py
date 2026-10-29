"""SEC discovery and cached downloads; original URLs and byte hashes are retained."""

import json
import time
from pathlib import Path

import httpx

from .files import atomic_json, digest, write_jsonl
from .models import Filing


def discover(
    raw_dir: Path, user_agent: str, companies=None, report_count=3, refresh_submissions=False
) -> list[Filing]:
    filings = []
    if companies is None:
        companies = json.loads((raw_dir.parent.parent / "configs/companies.json").read_text())
    raw_dir.mkdir(parents=True, exist_ok=True)
    with httpx.Client(headers={"User-Agent": user_agent}, timeout=60) as client:
        for company in companies:
            ticker, cik = company["ticker"], int(company["cik"])
            path = raw_dir / f"{ticker}_submissions.json"
            if not path.exists() or refresh_submissions:
                response = client.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
                response.raise_for_status()
                path.write_bytes(response.content)
                time.sleep(0.3)
            data = json.loads(path.read_text())
            recent = data["filings"]["recent"]
            main_indices = [i for i, form in enumerate(recent["form"]) if form == "10-K"][
                :report_count
            ]
            if len(main_indices) != report_count:
                raise ValueError(
                    f"{ticker}: fewer than {report_count} recent 10-Ks; inspect historical manifests"
                )
            main_accessions = {}
            for i in main_indices:
                end = recent["reportDate"][i]
                year = int(end[:4])
                accession = recent["accessionNumber"][i]
                filing = Filing(
                    id=f"{ticker}_FY{year}",
                    ticker=ticker,
                    cik=cik,
                    fiscal_year=year,
                    form="10-K",
                    accession=accession,
                    period_end=end,
                    filed_at=recent["filingDate"][i],
                    source_url=f"https://www.sec.gov/Archives/edgar/data/{cik}/"
                    f"{accession.replace('-', '')}/{recent['primaryDocument'][i]}",
                )
                filings.append(filing)
                main_accessions[end] = filing.id
            for i, form in enumerate(recent["form"]):
                end = recent["reportDate"][i]
                if form == "10-K/A" and end in main_accessions:
                    accession = recent["accessionNumber"][i]
                    filings.append(
                        Filing(
                            id=f"{main_accessions[end]}_A_{accession}",
                            ticker=ticker,
                            cik=cik,
                            fiscal_year=int(end[:4]),
                            form=form,
                            accession=accession,
                            period_end=end,
                            filed_at=recent["filingDate"][i],
                            amends_document_id=main_accessions[end],
                            source_url=f"https://www.sec.gov/Archives/edgar/data/{cik}/"
                            f"{accession.replace('-', '')}/{recent['primaryDocument'][i]}",
                        )
                    )
    return filings


def download(filings: list[Filing], raw_dir: Path, user_agent: str) -> list[Filing]:
    with httpx.Client(
        headers={"User-Agent": user_agent}, timeout=90, follow_redirects=True
    ) as client:
        for filing in filings:
            path = raw_dir / f"{filing.id}.html"
            if not path.exists():
                response = client.get(filing.download_url or filing.source_url)
                response.raise_for_status()
                if len(response.content) < 15000 or "<html" not in response.text[:1000].lower():
                    raise ValueError(f"Unexpected response for {filing.id}")
                path.write_bytes(response.content)
                time.sleep(0.4)
            filing.sha256 = digest(path.read_bytes())
            print(f"downloaded {filing.id}: {path.stat().st_size:,} bytes", flush=True)
    return filings


def acquire(root: Path, user_agent: str, refresh_manifest=False):
    raw_dir = root / "data/raw"
    manifest = root / "data/sources.jsonl"
    if manifest.exists() and not refresh_manifest:
        from .files import read_jsonl

        filings = [Filing(**r) for r in read_jsonl(manifest)]
    else:
        filings = discover(raw_dir, user_agent, refresh_submissions=refresh_manifest)
        if manifest.exists():
            # Keep historical filings for released evaluations; refresh adds available reports.
            from .files import read_jsonl

            previous = [Filing(**r) for r in read_jsonl(manifest)]
            filings = list({f.accession: f for f in [*previous, *filings]}.values())
        write_jsonl(manifest, [f.model_dump() for f in filings])
    filings = download(filings, raw_dir, user_agent)
    write_jsonl(manifest, [f.model_dump() for f in filings])
    atomic_json(
        root / "data/source_summary.json",
        {
            "main_reports": sum(f.form == "10-K" for f in filings),
            "amendments": sum(f.form == "10-K/A" for f in filings),
            "latest_filed_at": max(f.filed_at for f in filings),
            "refresh_manifest": refresh_manifest,
            "query_cutoff": "explicit as_of supplied separately",
            "identity": "SEC accession + sha256",
        },
    )
