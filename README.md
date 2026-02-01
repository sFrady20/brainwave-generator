# Brainwave Generator

Automated episode generation for Unity-based 3D cartoon livestreaming.

## Installation

```bash
# Create and activate environment
conda create -n brainwave python=3.11
conda activate brainwave

# Install package
pip install -e .
```

## Configuration

1. Copy `.env.example` to `.env` and add your OpenAI API key:
   ```
   OPENAI_API_KEY=sk-...
   ```

2. Optionally copy `config.example.yaml` to `config.yaml` to customize settings.

## Usage

```bash
# Generate a complete episode
brainwave generate --topic "The office WiFi goes down"

# Generate plot preview only (faster, for review before full generation)
brainwave preview --topic "Art discovers cryptocurrency"

# Build TTS audio for an episode
brainwave build <episode-id>        # Uses configured TTS provider
brainwave build <episode-id> --mock # Uses placeholder audio for testing

# Batch generate multiple episodes
brainwave batch -n 5

# Export Unity manifest
brainwave export <episode-id>

# List all episodes
brainwave list

# Show episode details
brainwave show <episode-id>
```

## Project Structure

```
src/brainwave/       # Main package
data/                # Character, shot, and voice definitions
templates/           # Jinja2 prompt templates
scenes/              # Generated episodes
placeholders/        # Mock audio files for testing
```

## TTS Providers

Configure in `config.yaml`:

- `mock` - Uses placeholder audio (no API calls)
- `openai` - OpenAI TTS API
- `local` - Local TTS (requires `pip install brainwave[local-tts]`)
