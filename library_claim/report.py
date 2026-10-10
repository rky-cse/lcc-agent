"""Plain human-readable report; all values come from serialized packet data."""

from html import escape
from urllib.parse import quote


def render_report(packet: dict) -> str:
    def text(value):
        return "Unknown" if value is None or value == "" else escape(str(value))

    def table(headers, rows):
        return "<table><thead><tr>" + "".join(f"<th>{escape(h)}</th>" for h in headers) + "</tr></thead><tbody>" + "".join(
            "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows) + "</tbody></table>"

    frame_paths = {x["id"]: x["path"] for x in packet["evidence_manifest"]}

    def frame(ref):
        return f'<a href="{quote(frame_paths[ref], safe="/")}">{escape(ref)}</a>'

    def price(p, key="amount"):
        if p[key] is None:
            return "Unpriced"
        return (text(p[key]) + f' <a href="{escape(p["url"], quote=True)}" rel="noopener noreferrer">'
                + text(p["source"]) + "</a><br>" + text(p["retrieved_at"])
                + "<br>Condition: " + text(p["condition_assumed"]))

    banner = "<p class='banner'>SYNTHETIC FIXTURE — not a real capture, quote or claim.</p>" if packet["synthetic"] else ""
    books = table(["ID / status", "Book", "Height / thickness cm", "Replacement", "Used", "Frame"], [
        [text(b["id"]) + " / " + text(b["status"]), text(b["title"]) + "<br>" + text(b["author"])
         + "<br>Edition: " + text(b["edition"]) + "<br>ISBN: " + text(b["isbn"]),
         text(b["spine_height_cm"]) + " / " + text(b["spine_thickness_cm"]),
         price(b["replacement_cost"]), price(b["used_value"]), frame(b["frame_ref"])]
        for b in packet["books"]])
    items = table(["ID / status", "Item", "Dimensions cm", "Replacement low / high", "Frame"], [
        [text(i["id"]) + " / " + text(i["status"]), text(i["category"]) + "<br>" + text(i["description"])
         + "<br>Brand / model: " + text(i["brand_model"]),
         " / ".join(text(i["dimensions_cm"][k]) for k in ("w", "h", "d")),
         price(i["replacement_cost"], "low") + " / " + text(i["replacement_cost"]["high"]), frame(i["frame_ref"])]
        for i in packet["items"]])
    facts = lambda data: table(["Field", "Value"], [[text(k), text(v)] for k, v in data.items()])
    review = table(["Reference", "Reason"], [[text(x["ref_id"]), text(x["reason"])] for x in packet["review_queue"]])
    evidence = table(["ID", "Saved evidence", "SHA-256"], [
        [text(x["id"]), f'<a href="{quote(x["path"], safe="/")}">{text(x["path"])}</a>', text(x["sha256"])]
        for x in packet["evidence_manifest"] + packet["quote_manifest"]])
    measurements = table(["ID / reference / field", "Value / unit", "Scale / derivation", "Frames"], [
        [text(m["id"]) + " / " + text(m["ref_id"]) + " / " + text(m["field"]),
         text(m["value"]) + " / " + text(m["unit"]), text(m["scale_method"]) + "<br>" + text(m["derivation"]),
         ", ".join(frame(ref) for ref in m["frame_refs"])] for m in packet["measurements"]])
    exclusions = table(["ID", "Reason"], [[text(x["id"]), "Reported as not owned; omitted from inventory and totals"]
                                         for x in packet["ownership_exclusions"]])
    return ("<!doctype html><html lang='en'><meta charset='utf-8'><title>Library contents claim packet</title>"
            "<style>body{font:16px system-ui;margin:24px;max-width:1200px}table{border-collapse:collapse;width:100%;margin-bottom:24px}"
            "th,td{border:1px solid #ccc;padding:8px;text-align:left;vertical-align:top;overflow-wrap:anywhere}"
            ".banner{background:#fff0bd;padding:12px;font-weight:bold}</style><body>"
            "<h1>Library contents claim packet</h1>" + banner
            + "<p>Status: " + text(packet["packet_status"]) + "; currency: " + text(packet["sweep"]["currency"]) + "</p>"
            + "<p>Unpriced/appraisal lines do not contribute to money totals. A zero subtotal can mean no priced lines. "
            "Confidence scores are upstream scores, not calibrated guarantees.</p>"
            + "<h2>Sweep</h2>" + facts(packet["sweep"]) + "<h2>Totals</h2>" + facts(packet["totals"])
            + "<h2>Valuation and measurement coverage</h2>" + facts(packet["coverage"])
            + "<h2>Aggregation policy</h2>" + facts(packet["aggregation_policy"])
            + "<h2>Books</h2>" + books + "<h2>Other contents</h2>" + items
            + "<h2>Room</h2>" + facts(packet["room"]) + "<h2>Review queue</h2>" + review
            + "<h2>Declared measurement evidence</h2><p>M01 validates record references, not physical measurement accuracy.</p>" + measurements
            + "<h2>Ownership exclusions</h2>" + exclusions
            + "<h2>Saved evidence</h2>" + evidence + "<p><a href='claim_packet.json'>Full JSON packet</a></p></body></html>")
