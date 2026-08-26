"""Extended Hosting Service entrypoint.

Imports the existing Flask application and attaches the runtime/deploy API without
changing the original account, billing, editor, or service lifecycle routes.
"""

from app import app, database, manager, project_files, rentals, settings
from rental_core.runtime_web import build_runtime_blueprint


if "runtime_api" not in app.blueprints:
    app.register_blueprint(
        build_runtime_blueprint(
            settings=settings,
            database=database,
            rentals=rentals,
            project_files=project_files,
            manager=manager,
        )
    )
