import json

from app.cmir.normalizer import normalize_inventory
from app.translators.aws import translate_cmir_to_aws
from app.generators.terraform import generate_aws_terraform
from app.config import AWS_OUTPUT_PATH, INVENTORY_PATH


def generate():

    with open(INVENTORY_PATH) as file:
        inventory = json.load(file)

    cmir = normalize_inventory(inventory)

    resources = translate_cmir_to_aws(cmir)

    terraform = generate_aws_terraform(resources)

    AWS_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(AWS_OUTPUT_PATH, "w") as file:
        file.write(terraform)

    print(f"Terraform generated: {AWS_OUTPUT_PATH}")


if __name__ == "__main__":
    generate()