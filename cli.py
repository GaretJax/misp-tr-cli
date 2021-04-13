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
    console = attr.ib()
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
    console = Console()

    misp_config = configparser.ConfigParser()
    misp_config.read_file(misp_configfile)
    misp_config = misp_config[misp_profile]

    misp_endpoint = misp_config["endpoint"]
    misp_api_key = misp_config["api_key"]
    misp_client = pymisp.PyMISP(misp_endpoint, misp_api_key)

    ctx.obj = App(console, misp_config, misp_client)


@main.command()
@click.pass_obj
def orgs(app):
    table = Table()
    table.add_column("ID", justify="right")
    table.add_column("Name", no_wrap=True)

    for obj in app.misp.organisations():
        org = obj["Organisation"]
        table.add_row(org["id"], org["name"])

    app.console.print(table)


@main.command()
@click.pass_obj
def tags(app):
    table = Table()
    table.add_column("ID", justify="right")
    table.add_column("Name", no_wrap=True)

    for obj in app.misp.tags():
        table.add_row(obj["id"], obj["name"])

    app.console.print(table)


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

    app.console.print(table)


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
        org=app.orgs_to_review, tags=[app.misp_config["threat_report_tag_id"]]
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
        status = ""
        tags = {t["id"] for t in e["Tag"]}

        approved = app.misp_config["approved_tag_id"] in tags

        if approved:
            status = Text("Approved", style="green bold")

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

        if e["id"] == "57":
            app.console.print(e)

    app.console.print(table)


if __name__ == "__main__":
    main()
