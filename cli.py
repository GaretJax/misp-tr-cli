#!/usr/bin/env python
import os

import configparser

import click
import attr
import pymisp
from rich.console import Console
from rich.table import Table


DEFAULT_MISP_CONFIGFILE = os.path.expanduser("~/.config/misp")
DEFAULT_MISP_PROFILE = "default"


@attr.s
class App:
    console = attr.ib()
    misp = attr.ib()


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

    misp_creds = configparser.ConfigParser()
    misp_creds.read_file(misp_configfile)

    misp_endpoint = misp_creds[misp_profile]["endpoint"]
    misp_api_key = misp_creds[misp_profile]["api_key"]
    misp_client = pymisp.PyMISP(misp_endpoint, misp_api_key)

    ctx.obj = App(console, misp_client)


@main.command()
@click.pass_obj
def orgs(app):
    table = Table()
    table.add_column("ID", justify="right")
    table.add_column("Name", no_wrap=True)

    for org in app.misp.organisations():
        org = org["Organisation"]
        table.add_row(org["id"], org["name"])

    app.console.print(table)


@main.command()
@click.pass_obj
def reviewable(app):
    events = app.misp.search(org=[20, 11, 5, 18, 27], tags=[28])

    for e in events:
        e = e["Event"]

        to_review = True

        for t in e.get("Tag"):
            if t["name"] == "yt_info_request":
                # Check if additional information has been provided
                import ipdb

                ipdb.set_trace()
                to_review = False
                break
            elif t["name"] == "yt_approved_event":
                to_review = False

        if not to_review:
            continue

        print(e["Org"]["name"], e["info"])


if __name__ == "__main__":
    main()
