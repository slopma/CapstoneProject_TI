import json
from pathlib import Path

from app.cmir.normalizer import normalize_inventory
from app.translators.aws import translate_cmir_to_aws
from app.generators.terraform import generate_aws_terraform


def generate():

    inventory_path = Path("inventory/onprem-example.json")
    output_path = Path("generated/aws/main.tf")

    with open(inventory_path) as file:
        inventory = json.load(file)

    cmir = normalize_inventory(inventory)

    resources = translate_cmir_to_aws(cmir)

    terraform = generate_aws_terraform(resources)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as file:
        file.write(terraform)

    print(f"Terraform generated: {output_path}")


if __name__ == "__main__":
    generate()