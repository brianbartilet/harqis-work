import argparse
import json
import requests


def main():
    parser = argparse.ArgumentParser(description='Send task to Flower API')

    parser.add_argument('--task', required=True,
                        help='Celery task full name, e.g. workflows.hud.tasks.hud_forex.show_forex_account')

    parser.add_argument('--args', nargs='*', default=[],
                        help='Positional arguments (space-separated).')

    parser.add_argument('--kwargs', nargs='*', default=[],
                        help='Keyword args in the form key="value" (space-separated).')

    parser.add_argument('--url', default='http://localhost:5555/api',
                        help='Flower API base URL, default http://localhost:5555/api')

    parser.add_argument('--user', help='Flower basic auth user')
    parser.add_argument('--password', help='Flower basic auth password')

    parsed = parser.parse_args()

    # Build kwargs dict from key="value" tokens
    kwarg_dict = {}
    for pair in parsed.kwargs:
        if '=' not in pair:
            continue
        key, value = pair.split('=', 1)
        # strip surrounding quotes if present
        value = value.strip().strip('"').strip("'")
        kwarg_dict[key] = value

    payload = {
        "args": parsed.args,
        "kwargs": kwarg_dict,
    }

    apply_url = f"{parsed.url}/task/async-apply/{parsed.task}"

    auth = (parsed.user, parsed.password) if parsed.user and parsed.password else None

    print(">> POST", apply_url)
    print(">> Payload:", json.dumps(payload))

    resp = requests.post(
        apply_url,
        json=payload,  # <-- send as JSON, not form-encoded
        auth=auth,
    )

    print("<< Status:", resp.status_code)
    try:
        print("<< JSON:", resp.json())
    except Exception:
        print("<< Text:", resp.text)


if __name__ == "__main__":
    main()
