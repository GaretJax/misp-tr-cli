#!/usr/bin/env python3
import os
import datetime
import time
import configparser
import logging
import webbrowser
from urllib.parse import urljoin
import statistics

import arrow
import click
import attr
import pymisp

from rich.live import Live
from rich.console import Console
from rich.table import Table
from rich.text import Text


DEFAULT_MISP_CONFIGFILE = os.path.expanduser("~/.config/misp")
DEFAULT_MISP_PROFILE = "default"
DATETIME_FORMAT = "MM/DD HHmm[Z]"
DISTRIBUTION_OWN_ORG_ONLY = 0
DISTRIBUTION_SHARING_GROUP = 4


class TimestampType(click.ParamType):
    name = "timestamp"

    def convert(self, value, param, ctx):
        if not value.endswith("Z"):
            self.fail("expected time in Zulu time zone")

        if len(value) != 5:
            self.fail("please only provide the time in HHMM format")

        hours, minutes = value[:2], value[2:4]
        time = datetime.time(int(hours), int(minutes))

        timestamp = datetime.datetime.combine(datetime.date.today(), time)
        return arrow.get(timestamp, datetime.timezone.utc)


@attr.s
class App:
    _click_context = attr.ib()
    stdout = attr.ib()
    stderr = attr.ib()
    misp_config = attr.ib()
    misp = attr.ib()

    @property
    def orgs_to_review(self):
        return list(self.orgs_with_sharing_groups.keys())

    @property
    def orgs_with_sharing_groups(self):
        return dict(
            [
                [int(id) for id in o.strip().split(":")]
                for o in self.misp_config["orgs_to_review_ids"]
                .strip()
                .splitlines()
            ]
        )

    def abort(self, error_message=None, code=1, style="red bold"):
        if error_message:
            self.stderr.print(error_message, style=style)
        self._click_context.exit(code=code)


@click.group()
@click.option(
    "--misp-configfile",
    type=click.File(),
    envvar="MISP_CONFIGFILE",
    default=DEFAULT_MISP_CONFIGFILE,
)
@click.option(
    "--misp-profile",
    envvar="MISP_PROFILE",
    default=DEFAULT_MISP_PROFILE,
)
@click.pass_context
def main(ctx, misp_configfile, misp_profile):
    logger = logging.getLogger("pymisp")
    logger.disabled = True

    stdout = Console()
    stderr = Console(stderr=True)

    misp_config = configparser.ConfigParser()
    misp_config.read_file(misp_configfile)
    misp_config = misp_config[misp_profile]

    misp_endpoint = misp_config["endpoint"]
    misp_api_key = misp_config["api_key"]
    misp_client = pymisp.PyMISP(misp_endpoint, misp_api_key)

    ctx.obj = App(ctx, stdout, stderr, misp_config, misp_client)


@main.command()
@click.pass_obj
def orgs(app):
    table = Table()
    table.add_column("ID", justify="right")
    table.add_column("Name", no_wrap=True)
    table.add_column("Sharing groups")

    sharing_groups = {}
    for g in app.misp.sharing_groups():
        for sg in g["SharingGroupOrg"]:
            sharing_groups.setdefault(sg["org_id"], set()).add(
                sg["sharing_group_id"]
            )

    for org in app.misp.organisations(pythonify=True):
        table.add_row(
            org.id, org.name, ", ".join(sharing_groups.get(org.id, []))
        )

    app.stdout.print(table)


@main.command()
@click.pass_obj
def tags(app):
    table = Table()
    table.add_column("ID", justify="right")
    table.add_column("Name", no_wrap=True)

    for obj in app.misp.tags():
        table.add_row(obj["id"], obj["name"])

    app.stdout.print(table)


@main.command()
@click.pass_obj
@click.argument("event_id", type=int)
def browse(app, event_id):
    url = urljoin(app.misp_config["endpoint"], f"events/view/{event_id}")
    webbrowser.open(url)


@main.command()
@click.pass_obj
def key_events(app):
    key_event_object_uuid = app.misp_config["key_event_object_uuid"]

    table = Table(show_lines=True)
    table.add_column("ID", justify="right")
    table.add_column("Team", no_wrap=True)
    table.add_column("Published", no_wrap=True)
    table.add_column("Updated", no_wrap=True)
    table.add_column("Name")
    table.add_column("Capability")
    table.add_column("Impact")
    table.add_column("Status")
    # table.add_column("Overview")
    # table.add_column("Actions & Results")

    for e in app.misp.search(
        org=app.orgs_to_review, tags=[app.misp_config["key_event_tag_id"]]
    ):
        e = e["Event"]

        # Timestamps
        published = arrow.get(int(e["publish_timestamp"]))
        updated = arrow.get(int(e["timestamp"]))

        if updated > published:
            updated = Text(updated.format(DATETIME_FORMAT))
            updated.stylize("bold magenta")
        else:
            updated = ""
        published = published.format(DATETIME_FORMAT)

        # Attributes
        attributes = {}
        for obj in e["Object"]:
            if obj["template_uuid"] == key_event_object_uuid:
                for a in obj["Attribute"]:
                    attributes[a["object_relation"]] = a["value"]
        else:
            # Error, handle?
            pass

        # Row
        table.add_row(
            e["id"],
            e["Org"]["name"],
            published,
            updated,
            e["info"],
            attributes.get("capability"),
            attributes.get("impact-on-capability"),
            attributes.get("event-status"),
            # attributes.get("overview"),
            # attributes.get("actions-taken-and-results"),
        )

    app.stdout.print(table)


@attr.s
class ThreatReport:
    _event = attr.ib()
    _scores = attr.ib()
    status = attr.ib()
    _key_event = attr.ib()
    published = attr.ib()
    updated = attr.ib()

    STATUSES = {
        "new": Text("New", style="yellow bold"),
        "info-requested": Text("Info requested", style="red"),
        "updated": Text("Updated", style="blue bold"),
        "approved": Text("Approved", style="green"),
    }

    @property
    def id(self):
        return self._event["id"]

    @property
    def scores(self):
        return [int(s[1]) for s in sorted(self._scores)]

    @property
    def org_name(self):
        return self._event["Org"]["name"]

    @property
    def title(self):
        return self._event["info"]

    @property
    def is_scored(self):
        return bool(self._scores)

    @property
    def key_event_id(self):
        return self._key_event["id"] if self._key_event else None

    @property
    def formatted_status(self):
        return self.STATUSES[self.status]

    @property
    def overall_score(self):
        if not self.scores:
            return None
        weight = sum(i + 1 for i in range(len(self.scores)))
        score = (
            sum((i + 1) * s for i, s in enumerate(reversed(self.scores)))
            / weight
        )
        return score


def get_reports(
    app, orgs, only=None, since=None, until=None, require_score=None
):
    threat_report_object_uuid = app.misp_config["threat_report_object_uuid"]

    for e in app.misp.search(
        org=orgs,
        tags=[app.misp_config["threat_report_tag_id"]],
        include_context=True,
    ):
        e = e["Event"]

        # Timestamps
        published = arrow.get(int(e["publish_timestamp"]))
        updated = arrow.get(int(e["timestamp"]))

        # Key event
        key_event_uuid = e.get("extends_uuid")
        key_event = None
        if key_event_uuid:
            key_event = app.misp.get_event(key_event_uuid)
            if "Event" in key_event:
                key_event = key_event["Event"]
            else:
                key_event = None

        for a in e["Attribute"]:
            updated = max(updated, arrow.get(int(a["timestamp"])))

        # Attributes
        attributes = {}
        for obj in e["Object"]:
            updated = max(updated, arrow.get(int(obj["timestamp"])))
            if obj["template_uuid"] == threat_report_object_uuid:
                for a in obj["Attribute"]:
                    attributes[a["object_relation"]] = a["value"]
            for a in obj["Attribute"]:
                updated = max(updated, arrow.get(int(a["timestamp"])))

        if since and updated < since:
            continue

        if until and published > until:
            continue

        tags = {t["id"] for t in e.get("Tag", [])}

        approved = app.misp_config["approved_tag_id"] in tags
        if only and approved and "approved" not in only:
            continue

        status = "new"
        scores = []
        e = app.misp.get_event(e["id"], extended=True)["Event"]
        for subevent in e.get("extensionEvents", {}).values():
            if subevent["Orgc"]["id"] != app.misp_config["yt_org_id"]:
                continue
            se = app.misp.get_event(subevent["id"])["Event"]
            subtags = {t["id"] for t in se.get("Tag", [])}
            info_requested = app.misp_config["info_request_tag_id"] in subtags
            if info_requested:
                info_requested_at = arrow.get(int(se["publish_timestamp"]))
                if info_requested_at > updated:
                    status = "info-requested"
                else:
                    status = "updated"

            scored = app.misp_config["score_tag_id"] in subtags
            if scored:
                for obj in se["Object"]:
                    if (
                        obj["template_uuid"]
                        == app.misp_config["scoring_object_uuid"]
                    ):
                        score = None
                        comment = ""
                        for a in obj["Attribute"]:
                            if a["object_relation"] == "score":
                                score = a["value"]
                            elif a["object_relation"] == "comment":
                                comment = a["value"]

                        scores.append((int(obj["timestamp"]), score, comment))

        if approved:
            status = "approved"

        if updated > published:
            updated = Text(updated.format(DATETIME_FORMAT))
            updated.stylize("bold magenta")
        else:
            updated = ""
        published = published.format(DATETIME_FORMAT)

        if only and status not in only:
            continue

        if require_score is True and not scores:
            continue
        elif require_score is False and scores:
            continue

        yield ThreatReport(
            event=e,
            key_event=key_event,
            published=published,
            updated=updated,
            status=status,
            scores=scores,
        )


def get_reports_table(
    app, orgs, only=None, since=None, until=None, require_score=None
):
    table = Table(show_lines=True)
    table.add_column("ID", justify="right")
    table.add_column("Published", no_wrap=True)
    table.add_column("Updated", no_wrap=True)
    table.add_column("Status")
    table.add_column("Score", justify="right")
    table.add_column("Team", no_wrap=True)
    table.add_column("Key event", no_wrap=True)
    table.add_column("Name")

    for report in get_reports(app, orgs, only, since, until, require_score):
        # Row
        table.add_row(
            report.id,
            report.published,
            report.updated,
            report.formatted_status,
            ", ".join(str(s) for s in report.scores),
            report.org_name,
            report.key_event_id,
            report.title,
        )

    return table


@main.command()
@click.option("--live/--no-live")
@click.option("-o", "--only", multiple=True)
@click.option(
    "--since",
    type=TimestampType(),
    help="Only list events modified since the given time",
)
@click.option(
    "--until",
    type=TimestampType(),
    help="Only list events published before the given time",
)
@click.option("--unscored", is_flag=True, help="Only list unscored events")
@click.option("--scored", is_flag=True, help="Only list scored events")
@click.option("--team", help="ID of a single team to show events for")
@click.pass_obj
def reports(app, team, live, only, since, until, unscored, scored):
    require_score = None
    if scored:
        require_score = True
    elif unscored:
        require_score = False
    else:
        app.abort("--unscored and --scored are mutually exclusive")

    def get_table():
        return get_reports_table(
            app,
            orgs=[team] if team else app.orgs_to_review,
            only=only,
            since=since,
            until=until,
            require_score=require_score,
        )

    if live:
        with Live(get_table(), refresh_per_second=4) as live:
            while True:
                time.sleep(5)
                live.update(get_table())
    else:
        app.stdout.print(get_table())


@main.command()
@click.option(
    "--since",
    type=TimestampType(),
    help="Only list events modified since the given time",
)
@click.option(
    "--until",
    type=TimestampType(),
    help="Only list events published before the given time",
)
@click.argument("team_id", type=int)
@click.pass_obj
def team_report(app, team_id, since, until):
    table = Table(show_lines=True)
    table.add_column("ID", justify="right")
    table.add_column("Key event", no_wrap=True)
    table.add_column("Status")
    table.add_column("Scores", justify="right")
    table.add_column("Comments")

    reports_by_status = {k: 0 for k in ThreatReport.STATUSES}
    scores = []

    for report in get_reports(app, [team_id], since=since, until=until):
        reports_by_status[report.status] += 1
        table.add_row(
            report.id,
            report.key_event_id,
            report.formatted_status,
            ", ".join(str(s) for s in report.scores),
            "\n".join(s[2] for s in report._scores),
        )
        if report.overall_score is not None:
            scores.append(report.overall_score)

    app.stdout.print(table)

    table = Table(show_footer=True)
    table.add_column("Status", footer="Total")
    table.add_column(
        "Reports", justify="right", footer=str(sum(reports_by_status.values()))
    )
    for k, v in reports_by_status.items():
        table.add_row(ThreatReport.STATUSES[k], str(v))
    app.stdout.print(table)

    if scores:
        table = Table(show_header=False)
        table.add_column()
        table.add_column()
        table.add_row("Average", "{:.2f}".format(sum(scores) / len(scores)))
        table.add_row("Median", "{:.2f}".format(statistics.median(scores)))
        table.add_row("Stdev", "{:.2f}".format(statistics.stdev(scores)))
        app.stdout.print(table)


@main.command()
@click.argument("event_id", type=int)
@click.pass_obj
def approve(app, event_id):
    event = app.misp.get_event(event_id)["Event"]
    tags = {t["id"] for t in event["Tag"]}

    if app.misp_config["threat_report_tag_id"] not in tags:
        app.abort("This event is not a threat report.")

    if app.misp_config["approved_tag_id"] in tags:
        app.abort("This event is already approved.", style="yellow")

    app.misp.tag(event["uuid"], app.misp_config["approved_tag_id"], local=True)


@main.command()
@click.pass_obj
@click.argument("event_id", type=int)
def feedback(app, event_id):
    original_event = app.misp.get_event(event_id, pythonify=True)
    tags = {t.id for t in original_event.tags}
    if app.misp_config["threat_report_tag_id"] not in tags:
        app.abort("This event is not a threat report.")

    message = click.edit()
    if message is None:
        app.abort("Feedback request aborted.")

    # Create event
    feedback_event = pymisp.MISPEvent()
    feedback_event.info = f"Info request: {original_event.info}"
    feedback_event.extends_uuid = original_event.uuid
    feedback_event.distribution = DISTRIBUTION_SHARING_GROUP
    feedback_event.sharing_group_id = app.orgs_with_sharing_groups[
        original_event.org_id
    ]
    feedback_event = app.misp.add_event(feedback_event, pythonify=True)

    # Add tags
    app.misp.tag(
        feedback_event, app.misp_config["info_request_tag_id"], local=False
    )
    app.misp.tag(
        feedback_event, app.misp_config["approved_tag_id"], local=True
    )

    # Add attributes
    attribute = pymisp.MISPAttribute()
    attribute.category = "Other"
    attribute.type = "comment"
    attribute.value = message
    app.misp.add_attribute(feedback_event, attribute)

    # Publish
    app.misp.publish(feedback_event)

    app.stdout.print(
        f"Sent feedback via event {feedback_event.id}", style="green"
    )


def get_scoring_event(app, original_event, create=True):
    try:
        extension_events = original_event.extensionEvents
    except AttributeError:
        pass
    else:
        for subevent in extension_events.values():
            if subevent["Orgc"]["id"] != app.misp_config["yt_org_id"]:
                continue
            se = app.misp.get_event(subevent["id"], pythonify=True)
            try:
                subtags = {t.id for t in se.tags}
            except AttributeError:
                pass
            else:
                if app.misp_config["score_tag_id"] in subtags:
                    return se, False

    scoring_event = pymisp.MISPEvent()
    scoring_event.info = (
        f"Scoring TR-{original_event.id}: {original_event.info}"
    )
    scoring_event.extends_uuid = original_event.uuid
    scoring_event.distribution = DISTRIBUTION_OWN_ORG_ONLY
    return scoring_event, True


@main.command()
@click.pass_obj
@click.argument("event_id")
def score(app, event_id):
    original_event = app.misp.get_event(
        event_id, extended=True, pythonify=True
    )
    tags = {t.id for t in original_event.tags}
    if app.misp_config["threat_report_tag_id"] not in tags:
        app.abort("This event is not a threat report.")

    # Get data
    scorevalue = click.prompt(
        "Please enter a score between 0 (worst) and 12 (best)", type=int
    )

    justification = click.edit()
    if justification is None:
        app.abort("Scoring aborted.")

    # Create data structures
    scoring_event, created = get_scoring_event(app, original_event)

    scoring_object = pymisp.MISPObject("ls21-scoring-object")
    scoring_object.template_uuid = app.misp_config["scoring_object_uuid"]
    scoring_object.template_version = 1
    scoring_object.add_attribute("score", scorevalue, type="float")
    scoring_object.add_attribute("comment", justification, type="text")

    # Sync to MISP
    if created:
        scoring_event = app.misp.add_event(scoring_event, pythonify=True)
        app.misp.tag(
            scoring_event, app.misp_config["score_tag_id"], local=True
        )
    app.misp.add_object(scoring_event, scoring_object)

    app.stdout.print(
        f"Score added for event {original_event.id}", style="green"
    )


if __name__ == "__main__":
    main()
