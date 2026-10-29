"""Actual upstream PageIndex Markdown tree core plus source block mapping."""

from .files import atomic_json
from .vendor.pageindex_markdown import (
    build_tree_from_nodes,
    clean_tree_for_output,
    extract_node_text_content,
    extract_nodes_from_markdown,
)


def build_source_tree(filing, blocks):
    lines, mapping, section = [f"# {filing.id}"], {}, None
    for b in blocks:
        if b.section != section:
            section = b.section
            lines.append(f"## {section}")
        mapping[len(lines) + 1] = b.id
        # Escape accidental Markdown headings in source; headings are created only above.
        lines.extend("    " + line for line in b.text.splitlines())
        lines.append("")
    md = "\n".join(lines)
    nodes, md_lines = extract_nodes_from_markdown(md)
    flat = extract_node_text_content(nodes, md_lines)
    structure = clean_tree_for_output(build_tree_from_nodes(flat))
    source_nodes = []
    for i, node in enumerate(flat):
        end = flat[i + 1]["line_num"] if i + 1 < len(flat) else len(lines) + 1
        ids = [bid for line, bid in mapping.items() if node["line_num"] <= line < end]
        if ids:
            source_nodes.append(
                {"node_id": str(i + 1).zfill(4), "title": node["title"], "block_ids": ids}
            )
    return {"document_id": filing.id, "structure": structure, "source_nodes": source_nodes}


def export_trees(root, filings, blocks):
    trees = [build_source_tree(f, blocks[f.id]) for f in filings]
    atomic_json(root / "data/processed/pageindex_markdown_trees.json", trees)
    return trees
