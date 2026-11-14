"""PDFs generated from immutable snapshots; GridFS publication is read-back verified."""

import hashlib
from html import escape
from io import BytesIO

from gridfs import AsyncGridFSBucket, NoFile
from pymongo.errors import DuplicateKeyError
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from chainlex.audit.models import AuditConflict, AuditNotFound, digest


def build_pdf(snapshot: dict) -> bytes:
    buffer = BytesIO()
    styles = getSampleStyleSheet()
    styles["BodyText"].fontSize = 9
    styles["BodyText"].leading = 13
    styles["BodyText"].wordWrap = "CJK"
    story = []

    def paragraph(text, style="BodyText"):
        return Paragraph(escape(str(text)), styles[style])

    def add(text, style="BodyText"):
        story.append(paragraph(text, style))
        story.append(Spacer(1, 6))

    def section(title):
        story.append(Spacer(1, 12))
        add(title, "Heading2")

    def readable(value):
        return str(value).replace("_", " ").lower().capitalize()

    def table(headers, rows, widths):
        value = Table(
            [[paragraph(c) for c in row] for row in [headers, *rows]],
            colWidths=widths,
            repeatRows=1,
            hAlign="LEFT",
        )
        value.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5efed")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor("#25645c")),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ]
            )
        )
        story.append(value)

    add("CHAINLEX | COMPLIANCE AUDIT", "Title")
    add(f"{snapshot['kind']} / version {snapshot['version']}", "Heading2")
    add(
        "SCRIPTED DEMO: fictional institutions/corridors and predefined reasoning. "
        "Voyage embeddings and saved workflow state are real. No funds were moved."
    )
    story.append(HRFlowable(width="100%", color=colors.HexColor("#25645c")))
    add(f"Audit: {snapshot['audit_id']} | Tenant: {snapshot['tenant_id']}")
    add(f"Created: {snapshot['created_at']} | Initiated by: {snapshot['initiated_by']}")
    analysis, context = snapshot["analysis"], snapshot["context"]
    section("Executive assessment")
    add(f"Verdict: {snapshot['verdict']}", "Heading3")
    add(f"Suggested route: {analysis['recommended_route_id'] or 'No suitable route'}")
    add(analysis["explanation"])
    if analysis.get("policy_proposal"):
        proposal = snapshot.get("policy_proposal") or analysis["policy_proposal"]
        add(
            f"Guardrail suggestion: {proposal['proposal_id']} / {proposal['status']}. "
            "Report sign-off does not approve a policy change."
        )
        if proposal.get("decided_by"):
            add(
                f"Policy decision by {proposal['decided_by']}: "
                f"{proposal.get('decision_reason', '')}"
            )
    if snapshot["verdict"] == "HUMAN_REJECTED":
        add(
            "The suggested route above is retained as proposal history. Human rejection "
            "means this audit does not recommend proceeding."
        )
    add(f"Asset: {context['asset']} | Amount: {context['amount']} | Network: {context['network']}")
    add(context["narrative"])
    add(f"Input adapter: {context['adapter']}")
    section("Route comparison and checks for each leg")
    for route in analysis["routes"]:
        add(f"{route['route_id']} | {route['outcome']}", "Heading3")
        add(" -> ".join(f"{b['bank_id']} ({b['jurisdiction']})" for b in route["banks"]))
        add(f"Origin: {route['provenance']}. Admission checks use fictional demo policies.")
        table(
            ["Bank / position", "Outcome", "Reason"],
            [
                [
                    f"{b['bank_id']} / {b['position'] + 1}",
                    readable(b["outcome"]),
                    readable(b["reason"]),
                ]
                for b in route["bank_checks"]
            ],
            [155, 95, 282],
        )
        for check in route["jurisdiction_checks"]:
            add(
                f"{check['jurisdiction']}: {check['outcome']} - {check['reason']}; "
                f"rules: {', '.join(check['rule_ids']) or 'none verified'}"
            )
        add("Outstanding checks: " + ", ".join(route["issues"]))
    section("Evidence, sources and limitations")
    add(
        f"Regulation retrieval: {snapshot['evidence']['regulation_search_status']}; "
        f"memory retrieval: {snapshot['evidence']['memory_search_status']}"
    )
    for source in context["sources"]:
        add(
            f"{source['source_id']} / {source['jurisdiction']}: {source['title']} "
            f"[{source['review_status']}; {source['provenance']}]"
        )
        add(source["url"])
    for rule in snapshot["evidence"].get("regulations", []):
        add(
            f"Retrieved rule: {rule['rule_id']} | {rule.get('title', '')} | "
            f"{rule.get('source_url', '')} | content hash: {rule.get('text_hash', '')}"
        )
    add(
        "Public-source fixture references are not live web research or proof of bank connectivity. "
        "Recommendations remain conditional on evidence and applicability review. "
        "Fees and settlement times have not been estimated."
    )
    section("Agent identity, policy and authority")
    if snapshot.get("policy"):
        add(
            f"Authorization policy version: {snapshot['policy']['version']} / "
            f"digest: {digest(snapshot['policy'])} / "
            f"approved by: {snapshot['policy']['approved_by']}"
        )
    for agent in snapshot["agents"]:
        add(f"{agent['agent_id']}: {agent['name']} / {agent['statement']} / scripted_demo")
    for event in snapshot["events"]:
        if event["event_type"] in {"ACTION_PERMITTED", "ACTION_DENIED"}:
            payload = event["payload"]
            add(
                f"{event['actor_id']} / {payload['action']} / allowed={payload['allowed']} / "
                f"policy v{payload['policy_version']} / authority={payload.get('authority')} / "
                f"input={payload['input_digest']}"
            )
    section("Governed memory and behavioral comparison")
    comparison = analysis["memory_comparison"]
    add(f"Behavior changed: {comparison['behavior_changed']}. {comparison['interpretation']}")
    add(
        f"Without memory: {comparison['without_memory']['recommended_route_id']}; "
        f"with memory: {comparison['with_memory']['recommended_route_id']}"
    )
    baseline = {r["route_id"]: r for r in comparison["without_memory"]["routes"]}
    for route in comparison["with_memory"]["routes"]:
        before = baseline[route["route_id"]]["unresolved_checks"]
        if before != route["unresolved_checks"]:
            add(
                f"Memory effect for {route['route_id']}: unresolved checks "
                f"{before} -> {route['unresolved_checks']}; "
                "a precedent-driven human gate was added."
            )
    for memory in snapshot["evidence"].get("memories", []):
        add(f"{memory['memory_id']} v{memory['version']} / {memory['content_hash']}")
        add(memory["narrative"])
        add(f"Required review: {memory['required_gate']}; expires {memory['valid_until']}")
    section("Human gates and recorded decisions")
    for gate in snapshot["gates"]:
        add(f"{gate['title']} | {gate['status']}", "Heading3")
        add(gate["reason"])
        add(
            f"Decision: {gate.get('decision_reason') or 'Pending'} | "
            f"Actor: {gate.get('actor_id') or '-'} | Time: {gate.get('decided_at') or '-'}"
        )
    section("Audit timeline and recovery")
    for event in snapshot["events"]:
        add(
            f"{event['sequence']}. {event['occurred_at']} / "
            f"{event['actor_id']} / {event['event_type']}"
        )
        if event["event_type"] in {
            "STEP_RETRY_SCHEDULED",
            "MANUAL_REVIEW_REQUIRED",
            "RETRY_REQUESTED",
        }:
            add(str(event["payload"]))
    section("Integrity and report scope")
    add(f"Analysis digest: {snapshot['analysis_digest']}")
    add(f"Snapshot digest: {digest(snapshot)}")
    add(
        f"Timeline through event {snapshot['events'][-1]['sequence']}. "
        "The publication receipt and PDF SHA-256 are available in the report manifest/export; "
        "they are recorded after these bytes are generated."
    )

    def footer(canvas, doc):
        canvas.setFont("Helvetica", 8)
        canvas.drawString(40, 24, f"ChainLex | {snapshot['kind']} | scripted demo")
        canvas.drawRightString(572, 24, f"Page {doc.page}")

    doc = SimpleDocTemplate(
        buffer,
        pagesize=(612, 792),
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=42,
        title="ChainLex compliance audit",
        author="ChainLex",
        invariant=1,
    )
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()


class ReportStore:
    def __init__(self, database):
        self.db = database
        self.bucket = AsyncGridFSBucket(database, bucket_name="audit_report_files")

    async def exists(self, file_id):
        try:
            await self.bucket.open_download_stream(file_id)
            return True
        except NoFile:
            return False

    async def probe(self, file_id, snapshot):
        try:
            saved = await self.bucket.open_download_stream(file_id)
            payload = await saved.read()
        except NoFile:
            return None
        actual = hashlib.sha256(payload).hexdigest()
        snapshot_hash = digest(snapshot)
        if (
            saved.metadata.get("snapshot_hash") != snapshot_hash
            or saved.metadata.get("sha256") != actual
        ):
            raise AuditConflict("Report read-back integrity check failed")
        return {
            "file_id": file_id,
            "sha256": actual,
            "byte_length": len(payload),
            "snapshot_hash": snapshot_hash,
            "verified": True,
        }

    async def publish(self, tenant, audit_id, version, snapshot, file_id):
        snapshot_hash = digest(snapshot)
        try:
            existing = await self.bucket.open_download_stream(file_id)
            payload = await existing.read()
        except NoFile:
            payload = build_pdf(snapshot)
            try:
                await self.bucket.upload_from_stream_with_id(
                    file_id,
                    f"{audit_id}-v{version}.pdf",
                    payload,
                    metadata={
                        "tenant_id": tenant,
                        "audit_id": audit_id,
                        "version": version,
                        "snapshot_hash": snapshot_hash,
                        "sha256": hashlib.sha256(payload).hexdigest(),
                    },
                )
            except DuplicateKeyError:
                # Another fenced/recovering publisher may already have saved this identity.
                pass
        saved = await self.bucket.open_download_stream(file_id)
        confirmed = await saved.read()
        actual = hashlib.sha256(confirmed).hexdigest()
        if (
            confirmed != payload
            or saved.metadata.get("snapshot_hash") != snapshot_hash
            or saved.metadata.get("sha256") != actual
        ):
            raise AuditConflict("Report read-back integrity check failed")
        return {
            "file_id": file_id,
            "sha256": actual,
            "byte_length": len(confirmed),
            "snapshot_hash": snapshot_hash,
            "verified": True,
        }

    async def list(self, tenant, audit_id):
        return [
            record
            async for record in self.db.audit_reports.find(
                {"tenant_id": tenant, "audit_id": audit_id}, {"_id": 0, "snapshot": 0}
            ).sort("version", 1)
        ]

    async def download(self, tenant, audit_id, version):
        record = await self.db.audit_reports.find_one(
            {"tenant_id": tenant, "audit_id": audit_id, "version": version}
        )
        if record is None:
            raise AuditNotFound("Report version is not published")
        file = await self.bucket.open_download_stream(record["file_id"])
        payload = await file.read()
        if hashlib.sha256(payload).hexdigest() != record["sha256"]:
            raise AuditConflict("Stored report integrity check failed")
        return payload
