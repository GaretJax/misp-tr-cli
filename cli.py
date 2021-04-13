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
def key_events(app):
    table = Table()
    table.add_column("ID", justify="right")
    table.add_column("Team", no_wrap=True)
    table.add_column("Name")

    for e in app.misp.search(
        org=app.orgs_to_review, tags=[app.misp_config["key_event_tag_id"]]
    ):
        e = e["Event"]
        table.add_row(e["id"], e["info"], e["Org"]["name"])
        # app.console.print(e)

    app.console.print(table)


if __name__ == "__main__":
    main()
