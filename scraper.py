import csv
import json
import time
import urllib.request
from urllib.error import HTTPError
from optparse import OptionParser
import re
from bs4 import BeautifulSoup  # Ensure this is used for extracting descriptions

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/35.0.1916.47 Safari/537.36"


def extract_quantity_and_unit(title):
    patterns = [
        r"(\d+(?:\.\d+)?)\s*(ml|g|kg|l|oz|lbs)",  # 100ml, 50g, 1.5kg, 2l, 3oz, 2lbs
        r"(\d+(?:\.\d+)?)\s*(pack|pcs|pieces)",  # 2 pack, 3pcs, 4 pieces
    ]

    for pattern in patterns:
        match = re.search(pattern, title, re.IGNORECASE)
        if match:
            quantity = float(match.group(1))
            unit = match.group(2).lower()
            return quantity, unit

    return None, None


def calculate_price_per_unit(product):
    quantity, unit = extract_quantity_and_unit(product["title"])

    if not quantity:
        for variant in product["variants"]:
            quantity, unit = extract_quantity_and_unit(variant["title"])
            if quantity:
                break

    if quantity and unit:
        price = float(product["variants"][0]["price"])
        price_per_unit = price / quantity
        return price_per_unit, unit

    return None, None


def get_page(url, page, collection_handle=None):
    full_url = url
    if collection_handle:
        full_url += "/collections/{}".format(collection_handle)
    full_url += "/products.json"
    req = urllib.request.Request(
        full_url + "?page={}".format(page),
        data=None,
        headers={"User-Agent": USER_AGENT},
    )
    while True:
        try:
            data = urllib.request.urlopen(req).read()
            break
        except HTTPError:
            print("Blocked! Sleeping...")
            time.sleep(180)
            print("Retrying")

    products = json.loads(data.decode())["products"]
    return products


def get_page_collections(url):
    full_url = url + "/collections.json"
    page = 1
    while True:
        req = urllib.request.Request(
            full_url + "?page={}".format(page),
            data=None,
            headers={"User-Agent": USER_AGENT},
        )
        while True:
            try:
                data = urllib.request.urlopen(req).read()
                break
            except HTTPError:
                print("Blocked! Sleeping...")
                time.sleep(180)
                print("Retrying")

        cols = json.loads(data.decode())["collections"]
        if not cols:
            break
        for col in cols:
            yield col
        page += 1


def check_shopify(url):
    try:
        get_page(url, 1)
        return True
    except Exception:
        return False


def fix_url(url):
    fixed_url = url.strip()
    if not fixed_url.startswith("http://") and not fixed_url.startswith("https://"):
        fixed_url = "https://" + fixed_url

    return fixed_url.rstrip("/")


def extract_products_collection(url, col):
    page = 1
    products = get_page(url, page, col)
    while products:
        for product in products:
            product.pop("body_html", None)
            price_per_unit, unit = calculate_price_per_unit(product)
            if price_per_unit:
                product["price_per_unit"] = f"{price_per_unit:.2f} per {unit}"
            else:
                product["price_per_unit"] = "N/A"

            # Extract and strip the body_html for the description
            product["description"] = strip_tags(
                product.get("body_html", "")
            )  # Add this line

            yield product
        page += 1
        products = get_page(url, page, col)


def strip_tags(html):
    return BeautifulSoup(html, "html.parser").get_text()


def extract_products(url, path, collections=None):
    # Use BeautifulSoup to strip HTML tags

    products_array = []  # Initialize an array to store all products

    with open(path, "w") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "Code",
                "Collection",
                "Category",
                "Name",
                "Variant Name",
                "Price",
                "Price per Unit",
                "In Stock",
                "URL",
                "Image URL",
                "Vendor",
                "Description",  # Add Description to the header
            ]
        )
        seen_variants = set()
        for col in get_page_collections(url):
            if collections and col["handle"] not in collections:
                continue
            handle = col["handle"]
            title = col["title"]
            for product in extract_products_collection(url, handle):
                # Add the full product to the array
                products_array.append(product)

                for variant in product["variants"]:
                    variant_id = variant["id"]
                    if variant_id in seen_variants:
                        continue

                    seen_variants.add(variant_id)
                    writer.writerow(
                        [
                            variant["sku"],
                            str(title),
                            product["product_type"],
                            product["title"],
                            variant["title"],
                            variant["price"],
                            product["price_per_unit"],
                            "Yes" if variant["available"] else "No",
                            f"{url}/products/{product['handle']}",
                            product["images"][0]["src"] if product["images"] else "",
                            product["vendor"],
                            strip_tags(
                                product.get("body_html", "")
                            ),  # Add this line to include the description
                        ]
                    )

    # Write the products array to a JSON file
    json_path = path.rsplit(".", 1)[0] + ".json"
    with open(json_path, "w") as json_file:
        json.dump(products_array, json_file, indent=2)

    return products_array  # Return the array of products


if __name__ == "__main__":
    parser = OptionParser()
    parser.add_option(
        "--list-collections",
        dest="list_collections",
        action="store_true",
        help="List collections in the site",
    )
    parser.add_option(
        "--collections",
        "-c",
        dest="collections",
        default="",
        help="Download products only from the given collections (comma separated)",
    )
    (options, args) = parser.parse_args()
    if len(args) > 0:
        url = fix_url(args[0])
        if options.list_collections:
            for col in get_page_collections(url):
                print(col["handle"])
        else:
            collections = []
            if options.collections:
                collections = options.collections.split(",")
            products = extract_products(url, "products.csv", collections)
            print(f"Total products extracted: {len(products)}")
