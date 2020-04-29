from cleo import argument
from cleo import option

from .env_command import EnvCommand
from .init import InitCommand


class AddCommand(EnvCommand, InitCommand):

    name = "add"
    description = "Adds a new dependency to <comment>pyproject.toml</>."

    arguments = [argument("name", "The packages to add.", multiple=True)]
    options = [
        option("dev", "D", "Add as a development dependency."),
        option(
            "extras",
            "E",
            "Extras to activate for the dependency.",
            flag=False,
            multiple=True,
        ),
        option("optional", None, "Add as an optional dependency."),
        option(
            "python",
            None,
            "Python version for which the dependency must be installed.",
            flag=False,
        ),
        option(
            "platform",
            None,
            "Platforms for which the dependency must be installed.",
            flag=False,
        ),
        option("allow-prereleases", None, "Accept prereleases."),
        option(
            "dry-run",
            None,
            "Output the operations but do not execute anything (implicitly enables --verbose).",
        ),
        option(
            "editable",
            None,
            "Install a local source package to the environment in editable mode.",
        ),
    ]

    help = """The add command adds required packages to your <comment>pyproject.toml</> and installs them.

If you do not specify a version constraint, poetry will choose a suitable one based on the available package versions.
"""

    loggers = ["poetry.repositories.pypi_repository"]

    def _write_editable_uninstall_commands(self, requirements):
        editable_uninstall = """
This packages were installed in <info>editable mode</> and were not included on
pyproject.toml and poetry.lock.

To uninstall them use:
<info>{}</>
"""
        commands = [" * pip uninstall {}".format(r['name']) for r in requirements]
        self.io.write(editable_uninstall.format("\n".join(commands)))

    def handle(self):
        from poetry.installation.installer import Installer
        from poetry.semver import parse_constraint
        from tomlkit import inline_table

        packages = self.argument("name")
        is_dev = self.option("dev")

        if self.option("extras") and len(packages) > 1:
            raise ValueError(
                "You can only specify one package " "when using the --extras option"
            )

        section = "dependencies"
        if is_dev:
            section = "dev-dependencies"

        original_content = self.poetry.file.read()
        content = self.poetry.file.read()
        poetry_content = content["tool"]["poetry"]

        if section not in poetry_content:
            poetry_content[section] = {}

        for name in packages:
            for key in poetry_content[section]:
                if key.lower() == name.lower():
                    pair = self._parse_requirements([name])[0]
                    if (
                        "git" in pair
                        or "url" in pair
                        or pair.get("version") == "latest"
                    ):
                        continue

                    raise ValueError("Package {} is already present".format(name))

        requirements = self._determine_requirements(
            packages, allow_prereleases=self.option("allow-prereleases")
        )

        for _constraint in requirements:
            if "version" in _constraint:
                # Validate version constraint
                parse_constraint(_constraint["version"])

            constraint = inline_table()
            for name, value in _constraint.items():
                if name == "name":
                    continue

                constraint[name] = value

            if self.option("optional"):
                constraint["optional"] = True

            if self.option("allow-prereleases"):
                constraint["allow-prereleases"] = True

            if self.option("extras"):
                extras = []
                for extra in self.option("extras"):
                    if " " in extra:
                        extras += [e.strip() for e in extra.split(" ")]
                    else:
                        extras.append(extra)

                constraint["extras"] = self.option("extras")

            if self.option("python"):
                constraint["python"] = self.option("python")

            if self.option("platform"):
                constraint["platform"] = self.option("platform")

            if len(constraint) == 1 and "version" in constraint:
                constraint = constraint["version"]

            poetry_content[section][_constraint["name"]] = constraint

        # Write new content
        self.poetry.file.write(content)

        # Cosmetic new line
        self.line("")

        # Update packages
        self.reset_poetry()

        installer = Installer(
            self.io, self.env, self.poetry.package, self.poetry.locker, self.poetry.pool
        )

        installer.dry_run(self.option("dry-run"))
        installer.editable(self.option("editable"))
        installer.update(True)
        installer.whitelist([r["name"] for r in requirements])

        try:
            status = installer.run()
        except Exception:
            self.poetry.file.write(original_content)

            raise

        need_revert_command = (
            self.option("dry-run") or
            self.option("editable")
        )
        if status != 0 or need_revert_command:
            # Revert changes
            if status != 0:
                self.error(
                    "\n"
                    "Addition failed, reverting pyproject.toml "
                    "to its original content."
                )
            elif self.option("editable"):
                self._write_editable_uninstall_commands(requirements)

            self.poetry.file.write(original_content)

        return status
