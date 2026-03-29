# Amazon Nova Debug Example

This folder contains a small `so-record` example that calls the Bedrock Converse API with an Amazon Nova model.

## API key setup

Use the normal AWS credential chain. The most direct environment-variable setup is:

```bash
export AWS_ACCESS_KEY_ID=your_access_key_id
export AWS_SECRET_ACCESS_KEY=your_secret_access_key
export AWS_REGION=us-east-1
```

If you are using temporary credentials, also export:

```bash
export AWS_SESSION_TOKEN=your_session_token
```

You can also use an existing AWS profile instead of raw keys:

```bash
export AWS_PROFILE=your_profile_name
export AWS_REGION=us-east-1
```

Make sure your account has Bedrock access to Amazon Nova in the target region.

## Run it

```bash
cd example_workflows/debug_examples/nova
uv run so-record debate.py
```

The script uses `amazon.nova-lite-v1:0` so the traced nodes exercise the new Nova display alias handling.
