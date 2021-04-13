#!/usr/bin/env python
import os
import configparser
import webbrowser
from urllib.parse import urljoin

import arrow
import click
import attr
import pymisp
from rich.console import Console
from rich.table import Table
from rich.text import Text


DEFAULT_MISP_CONFIGFILE = os.path.expanduser("~/.config/misp")
DEFAULT_MISP_PROFILE = "default"
DATETIME_FORMAT = "MM/DD HHMM[Z]"


@attr.s
class App:
    _click_context = attr.ib()
    stdout = attr.ib()
    stderr = attr.ib()
    misp_config = attr.ib()
    misp = attr.ib()

    @property
    def orgs_to_review(self):
        return [
            int(o.strip())
            for o in self.misp_config["orgs_to_review_ids"]
            .strip()
            .splitlines()
        ]

    def abort(self, error_message=None, code=1):
        if error_message:
            self.stderr.print(error_message, style="red bold")
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

    for obj in app.misp.organisations():
        org = obj["Organisation"]
        table.add_row(org["id"], org["name"])

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
                break
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


@main.command()
@click.pass_obj
def reports(app):
    threat_report_object_uuid = app.misp_config["threat_report_object_uuid"]

    table = Table(show_lines=True)
    table.add_column("ID", justify="right")
    table.add_column("Team", no_wrap=True)
    table.add_column("Published", no_wrap=True)
    table.add_column("Updated", no_wrap=True)
    table.add_column("Status")
    table.add_column("Name")
    # table.add_column("Capability")
    # table.add_column("Impact")
    # table.add_column("Status")

    for e in app.misp.search(
        org=app.orgs_to_review,
        tags=[app.misp_config["threat_report_tag_id"]],
        include_context=True,
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
            if obj["template_uuid"] == threat_report_object_uuid:
                for a in obj["Attribute"]:
                    attributes[a["object_relation"]] = a["value"]
                break
        else:
            # Error, handle?
            pass

        # Status
        tags = {t["id"] for t in e["Tag"]}

        approved = app.misp_config["approved_tag_id"] in tags

        status = Text("New", style="yellow bold")
        if approved:
            status = Text("Approved", style="green")
        else:
            e = app.misp.get_event(e["id"], extended=True)["Event"]
            for subevent in e.get("extensionEvents", {}).values():
                if subevent["Orgc"]["id"] != app.misp_config["yt_org_id"]:
                    continue
                se = app.misp.get_event(subevent["id"])["Event"]
                subtags = {t["id"] for t in se["Tag"]}
                info_requested = (
                    app.misp_config["info_request_tag_id"] in subtags
                )
                if info_requested:
                    status = Text("Info requested", style="red")
                    break

        # Row
        table.add_row(
            e["id"],
            e["Org"]["name"],
            published,
            updated,
            status,
            e["info"],
            # attributes.get("capability"),
            # attributes.get("impact-on-capability"),
            # attributes.get("event-status"),
            # attributes.get("overview"),
            # attributes.get("actions-taken-and-results"),
        )

    app.stdout.print(table)


@main.command()
@click.pass_obj
@click.argument("event_id", type=int)
def approve(app, event_id):
    event = app.misp.get_event(event_id)["Event"]
    tags = {t["id"] for t in event["Tag"]}

    if app.misp_config["threat_report_tag_id"] not in tags:
        app.abort("This event is not a threat report.")

    if app.misp_config["approved_tag_id"] in tags:
        app.abort("This event was already approved.")

    app.misp.tag(
        event["uuid"], app.misp_config["approved_tag_id"], local=True
    )


if __name__ == "__main__":
    main()
