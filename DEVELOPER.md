# Notes for Developers

## Setup Via Local Environment

See the [recommended VSCode extensions](vscode_extensions.md) for a better dev experience.

Being in repository directory:

```bash
python3.12 -m venv venv
vim venv/bin/activate
# Then add line at the end of file: export PYTHONPATH="$VIRTUAL_ENV/../src"

source venv/bin/activate
pip install --no-cache-dir -r requirements.txt -r requirements-dev.txt
```

## Pre-Commit Actions

Format & Lint & Type Check:

```bash
black src/
ruff check src/ --fix
mypy src/
```

## Bot Launch

Be sure to have `.env` file similar to `.env.example`.

Being in repository directory, give permissions:

```bash
sudo mkdir -p ./data/recsys/opensearch/data && sudo chown -R 1000:1000 ./data/recsys/opensearch/data
```

Being in repository directory, launch:

```bash
sudo systemctl start docker

docker compose build #--no-cache
docker compose up --detach --remove-orphans
```

Commands to stop:

```bash
docker compose stop
docker compose down
```

Note that the bot started in docker _synchronizes_ Postgres DB & logs with local directory via channeling.

### View logs

You can view logs from docker via:

```bash
docker compose logs -f bot
docker compose logs -f <bot/api/db/opensearch>
```

or in files at `./data/logs` path locally.

### Enter container

```bash
docker compose run -it bot bash
docker compose run -it <bot/api/db/opensearch> bash
```

---

Happy contributing! 💙
