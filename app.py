"""Flask app factory. Run with:  flask --app app run   (then open http://127.0.0.1:5000)"""
import os

import click
from flask import Flask

from models import db, current_date, Part
from money import fmt, fmt_price


def create_app(db_uri=None):
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "eng566-bookkeeper"
    default_db = "sqlite:///" + os.path.join(app.instance_path, "bookkeeper.db")
    app.config["SQLALCHEMY_DATABASE_URI"] = db_uri or os.environ.get("BOOKKEEPER_DB", default_db)
    os.makedirs(app.instance_path, exist_ok=True)
    db.init_app(app)

    app.jinja_env.filters["money"] = fmt
    app.jinja_env.filters["price"] = fmt_price
    app.jinja_env.filters["num"] = lambda n: f"{n:,}" if n is not None else ""

    from routes import bp
    app.register_blueprint(bp)

    @app.context_processor
    def inject_globals():
        try:
            low = [p.name for p in Part.query.all() if p.needs_reorder]
            return dict(today=current_date(), low_stock=low)
        except Exception:        # database not initialised yet
            return dict(today=None, low_stock=[])

    @app.cli.command("seed")
    @click.option("--preset", type=click.Choice(["fresh", "turnin"]), default="fresh",
                  help="fresh: $200k cash only. turnin: also opening stock of 40,000 trucks.")
    def seed_command(preset):
        """Reset the database to the initial conditions."""
        from seed import seed
        seed(preset)
        click.echo(f"Database reset ({preset}).")

    with app.app_context():
        from sqlalchemy import inspect
        if not inspect(db.engine).has_table("account"):
            from seed import seed
            seed("fresh")
    return app


if __name__ == "__main__":
    create_app().run(debug=True)
