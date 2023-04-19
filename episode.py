import os
import requests
import uuid
import paths
import re
import json
from tts import tts
from keys import open_ai_api_key
from datetime import datetime

beats = ["exposition", "rising action", "climax", "falling action", "resolution"]
scene_attempts = 3
models = {"plot": "gpt-4-0314", "script": "gpt-4-0314", "evaluation": "gpt-4-0314"}

character_map = [
    {
        "id": "Art",
        "patterns": [r"arthur", r"(?:^|\s|\")art(?:$|\s|\")", r"beechum"],
        "voice": "Rodney",
    },
    {
        "id": "Nia",
        "patterns": [r"(?:^|\s|\")nia(?:$|\s|\")", r"(?:^|\s|\")jones(?:$|\s|\")"],
        "voice": "Karen",
    },
    {
        "id": "Liam",
        "patterns": [r"(?:^|\s|\")liam(?:$|\s|\")", r"o.connel"],
        "voice": "Cillian",
    },
    {"id": "Marcus", "patterns": [r"marcus", r"okonkwo"], "voice": "Obinna"},
    {"id": "Marko", "patterns": [r"marko", r"russo"], "voice": "Bruce"},
    {
        "id": "Devika",
        "patterns": [r"devika", r"sharma", r"aisha", r"patel"],
        "voice": "Shilpa",
    },
    {
        "id": "Sam",
        "patterns": [r"(?:^|\s|\")sam(?:$|\s|\")", r"samantha", r"wilson"],
        "voice": "Jodie",
    },
    {"id": "Mike", "patterns": [r"mike", r"michael", r"jackson"], "voice": "Ronald"},
    {"id": "Dave", "patterns": [r"dave", r"david", r"kent"], "voice": "Tom"},
    {"id": "Carmen", "patterns": [r"carmen", r"vega", r"rodriguez"], "voice": "Mia"},
    {"id": "Rachel", "patterns": [r"rachel", r"johnson"], "voice": "Lisa"},
]


def get_prompt(name):
    with open(os.path.join(paths.prompts_dir, f"{name}.md"), "r") as f:
        return f.read()


def ask(message: str) -> bool:
    while True:
        user_input = input(
            f"\n{message}\n'y' or 'n':"
        ).lower()  # Convert user input to lowercase
        if user_input == "y":
            return True
        if user_input == "n":
            return False
        print("Invalid input. Please try again.")


class Episode:
    id = ""
    work_dir = ""
    assets_dir = ""
    sfx_dir = ""
    _debug = True

    def __init__(self, id: str = None):
        self.id = str(uuid.uuid4()) if not id else id

        self.work_dir = os.path.join(paths.scenes_dir, f"{self.id}")
        if not os.path.exists(self.work_dir):
            os.makedirs(self.work_dir)

        self.assets_dir = os.path.join(self.work_dir, "assets")
        if not os.path.exists(self.assets_dir):
            os.makedirs(self.assets_dir)

        self.sfx_dir = os.path.join(self.assets_dir, "sfx")
        if not os.path.exists(self.sfx_dir):
            os.makedirs(self.sfx_dir)

    def _read_file(self, name):
        with open(os.path.join(self.work_dir, f"{name}"), "r") as f:
            return f.read()

    def _write_file(self, name, str):
        with open(os.path.join(self.work_dir, name), "w") as f:
            f.write(str)

    def _gpt(
        self,
        messages: list,
        file_key: str,
        model: str,
        temperature: float = 1,
    ):
        if self._debug:
            self._write_file(
                f"{file_key}-prompt.txt",
                "\n\n".join(
                    [f"== {item['role']} ==\n{item['content']}" for item in messages]
                ),
            )

        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {open_ai_api_key}",
            },
            json={"model": model, "messages": messages, "temperature": temperature},
        )
        if response.status_code == 200:
            output = response.json()["choices"][0]["message"]["content"]
            if self._debug:
                self._write_file(f"{file_key}-response.txt", output)
            return output
        else:
            error = response.json()
            if self._debug:
                self._write_file(f"{file_key}-error.txt", json.dumps(error))
            raise Exception(f"ChatGPT error: {error['error']}")

    def generate(self, autoAccept=False):
        plot_path = os.path.join(
            paths.scenes_dir, f"{self.id}/episode-plot-response.txt"
        )

        plot: str = None

        if os.path.exists(plot_path):
            if (
                ask(
                    "A plot for this episode already exists would you like to skip plot generation?"
                )
                or autoAccept
            ):
                with open(plot_path, "r") as f:
                    plot = f.read()
            else:
                plot = self._generate_plot()
        else:
            plot = self._generate_plot()

        print(plot)
        if not (ask("Do you want to continue using this plot?")):
            raise Exception("cancelled")

        scripts = []
        prev_script_summary = None

        for step in range(5):
            try:
                for attempt in range(scene_attempts):
                    try:
                        # get scene plot
                        scene_plot = re.search(
                            re.compile(
                                r""
                                + beats[step]
                                + r"(?:\s*:\s*|\s*-\s*)(.+?)\s*(?:\n|$)",
                                re.IGNORECASE,
                            ),
                            plot,
                        ).group(1)

                        # generate script
                        [script, summary] = self._generate_script(
                            scene_id=step,
                            episode_plot=plot,
                            scene_plot=scene_plot,
                            prev_scene=prev_script_summary,
                        )
                        scripts = scripts.copy()
                        scripts.append(script)

                        # passing the summary to the next scene
                        prev_script_summary = summary
                        break
                    except Exception as e:
                        print(f"Error on step {step} (attempt {attempt + 1})", e)
                        if attempt == scene_attempts:
                            raise Exception(f"Failed on step {step}")
                        else:
                            continue
            except Exception as e:
                print("Error generating scene script:", e)
                break

        # format the script
        episode_script = "\n".join(scripts)
        episode_script = re.sub(
            r"\n\n+", "\n", episode_script
        )  # remove excess new lines

        # write entire script
        self._write_file("episode-script.txt", episode_script)

        print(f"📺 Episode {self.id} generated")

    def _generate_plot(self, autoAccept=False):
        print(f"generating episode {self.id}")

        plot_path = os.path.join(
            paths.scenes_dir, f"{self.id}/episode-plot-response.txt"
        )
        if os.path.exists(plot_path):
            if (
                ask(
                    "A plot for this episode already exists would you like to skip plot generation?"
                )
                or autoAccept
            ):
                with open(plot_path, "r") as f:
                    return f.read()

        # define prompt messages
        messages = [
            {"role": "system", "content": get_prompt("context")},
            {"role": "system", "content": get_prompt("description")},
            {"role": "system", "content": get_prompt("characters")},
            {"role": "system", "content": get_prompt("shots")},
            {"role": "user", "content": get_prompt("plot")},
        ]

        # make call to chatgpt
        return self._gpt(
            messages=messages,
            file_key="episode-plot",
            model=models["plot"],
            temperature=1.15,
        )

    def _generate_script(
        self,
        scene_id: int,
        episode_plot,
        scene_plot: str,
        prev_scene: str = None,
        autoAccept=False,
    ):
        print(f"generating script for scene {scene_id}")

        output: str = None
        skip: bool = False

        script_path = os.path.join(
            paths.scenes_dir, f"{self.id}/scene-{scene_id}-script-response.txt"
        )
        if os.path.exists(script_path):
            if (
                ask(
                    f"A script for scene {scene_id} already exists would you like to skip generation for this scene?"
                )
                or autoAccept
            ):
                skip = True
                with open(script_path, "r") as f:
                    output = f.read()

        if not skip:
            messages = [
                {"role": "system", "content": get_prompt("context")},
                {"role": "system", "content": get_prompt("description")},
                {"role": "system", "content": get_prompt("characters")},
                {"role": "system", "content": get_prompt("shots")},
                {"role": "system", "content": get_prompt("transitions")},
                {
                    "role": "system",
                    "content": f"For reference, here is the plot of the entire episode:\n{episode_plot}",
                },
                *(
                    [
                        {
                            "role": "system",
                            "content": f"This is the summary of the previous scene script. Use it for context and to recall important events and information:\n{prev_scene}",
                        }
                    ]
                    if prev_scene is not None
                    else []
                ),
                {
                    "role": "user",
                    "content": get_prompt("script").replace("((PLOT))", scene_plot),
                },
            ]

            # make call to chatgpt
            output = self._gpt(
                messages=messages,
                file_key=f"scene-{scene_id}-script",
                model=models["script"],
                temperature=1.1,
            )

        # extract summary
        match = re.compile(r"==summary==", re.IGNORECASE).search(output)
        if not match:
            raise Exception("There was an error parsing the summary")

        summary_index = match.start()
        summary = output[summary_index + len(match.group()) :].strip()

        script = output[:summary_index].strip()
        # format script
        script = re.sub(
            re.compile(r"dialog:\s+", re.IGNORECASE), "\n", script
        )  # remove dialog label
        script = re.sub(r"\n\n+", "\n", script)  # remove excess new lines
        script.replace("�", "")  # remove unknown characters

        return [script, summary]

    def evaluate(self):
        print(f"evaluating episode {self.id}")

        episode_script = self._read_file("episode-script.txt")

        messages = [
            {"role": "system", "content": get_prompt("characters")},
            {"role": "system", "content": get_prompt("shots")},
            {
                "role": "system",
                "content": f"the final script of the episode is:\n{episode_script}",
            },
            {"role": "user", "content": get_prompt("evaluation")},
        ]

        # make call to chatgpt
        return self._gpt(
            messages=messages,
            file_key="evaluation",
            model=models["evaluation"],
            temperature=0.5,
        )

    def build(self, mock=False):
        episode_script = self._read_file("episode-script.txt")
        lines = episode_script.splitlines()

        # build sfx using narakeet
        for line_number, line in enumerate(lines):
            matches = re.search(
                re.compile(r"^([\w\s]+?)\:\s*\((.+?)\)\s*(.+)$", re.IGNORECASE), line
            )

            if bool(matches):
                speaker = None

                # find character
                for character in character_map:
                    for pattern in character["patterns"]:
                        if bool(
                            re.search(
                                re.compile(pattern, re.IGNORECASE), matches.group(1)
                            )
                        ):
                            speaker = character
                            break

                if not speaker:
                    print(f"character not found '{matches.group(1)}'")
                    continue

                voice = speaker["voice"]
                dialog = matches.group(3)

                dialog = re.sub(r"\(.+?\)", "", dialog)  # remove parentheses

                print(f"processing line {line_number} with voice '{voice}' - {dialog}")
                tts(
                    dialog,
                    voice,
                    os.path.join(self.sfx_dir, f"dialog-{line_number}.mp3"),
                    mock=mock,
                )

        # save status and mark as complete
        with open(os.path.join(self.assets_dir, "/build.status.json"), "w") as f:
            json.dump({"complete": True, "completedAt": datetime.now().isoformat()})
