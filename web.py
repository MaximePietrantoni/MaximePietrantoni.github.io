import fnmatch
import requests
import re
import sys
import logging
import click
import tempfile
from functools import partial, lru_cache
from PIL import Image, ImageSequence
import os
try:
    from BeautifulSoup import BeautifulSoup
except ImportError:
    from bs4 import BeautifulSoup


def _setup_logging(verbose):
    class Formatter(logging.Formatter):
        def format(self, record: logging.LogRecord):
            levelname = record.levelname[0]
            message = record.getMessage()
            if levelname == "D":
                return f"\033[0;36mdebug:\033[0m {message}"
            elif levelname == "I":
                return f"\033[1;36minfo:\033[0m {message}"
            elif levelname == "W":
                return f"\033[0;1;33mwarning: {message}\033[0m"
            elif levelname == "E":
                return f"\033[0;1;31merror: {message}\033[0m"
            else:
                return message

    kwargs = {}
    if sys.version_info >= (3, 8):
        kwargs["force"] = True
    if verbose == "disabled":
        logging.basicConfig(level=logging.FATAL, **kwargs)
        logging.getLogger('PIL').setLevel(logging.FATAL)
        try:
            import tqdm as _tqdm  # type: ignore
            old_init = _tqdm.tqdm.__init__
            _tqdm.tqdm.__init__ = lambda *args, disable=None, **kwargs: old_init(*args, disable=True, **kwargs)
        except ImportError:
            pass
    elif verbose:
        logging.basicConfig(level=logging.DEBUG, **kwargs)
        logging.getLogger('PIL').setLevel(logging.WARNING)
    else:
        logging.basicConfig(level=logging.INFO, **kwargs)
    for handler in logging.root.handlers:
        handler.setFormatter(Formatter())
    logging.captureWarnings(True)


@lru_cache(1)
def _get_cite_counts():
    profile_url = "https://scholar.google.com/citations?user=YDNzfN4AAAAJ"

    def get_publication_id(title, year):
        fw = re.match(r"^[a-z]+", title.lower()).group(0)
        return f'{year}{fw}'

    response = requests.get(profile_url, headers={'User-Agent': 'Mozilla/5.0'})
    response.raise_for_status()
    parsed_html = BeautifulSoup(response.text, 'html.parser')

    records = parsed_html.body.findAll(attrs={'class':'gsc_a_tr'})
    output = {}
    for a in records:
        cite_count = a.find(attrs={'class': 'gsc_a_ac'}).text
        title = a.find(attrs={'class': 'gsc_a_at'}).text
        year = a.find(attrs={'class': 'gsc_a_y'}).text
        if cite_count:
            output[get_publication_id(title, year)] = int(cite_count)
    return output


def _load_bib(x):
    root = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(root, x), "r", encoding="utf8") as f:
        x = f.read()
    return x


def _transform_template(input_path, output_path, repo_path, data=None, base_path="", minify_html=True, **kwargs):
    del kwargs
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    base_path = base_path.strip("/")
    if base_path:
        base_path = f"/{base_path}"
    env = Environment(
        loader=FileSystemLoader(input_path),
        autoescape=select_autoescape()
    )
    env.filters["load_bib"] = _load_bib

    outrepopath = repo_path
    os.makedirs(os.path.dirname(output_path + outrepopath), exist_ok=True)
    with open(f"{output_path}{outrepopath}", "w", encoding="utf8") as f:
        template = env.get_template(outrepopath)
        html = template.render(**(data or (lambda: {}))(), base_path=base_path)
        if minify_html:
            from minify_html import minify  # type: ignore
            html = minify(html)
        f.write(html)
        f.flush()
        yield outrepopath


def _resize_image(input_path, output_path, repo_path, size, **kwargs):
    del kwargs
    w, h = size
    img = Image.open(input_path + repo_path)
    ow, oh = img.size
    if w < 0:
        w = int(round(abs(w) * (ow * h / oh))) // abs(w)
    if h < 0:
        h = int(round(abs(h) * (oh * w / ow))) // abs(h)

    # Central crop
    process = lambda x: x
    if ow / oh > w / h:
        process = partial(
            lambda p, x: p(x).crop(((ow - oh * w / h) / 2, 0, (ow + oh * w / h) / 2, oh)), 
            process)
    elif ow / oh < w / h:
        process = partial(
            lambda p, x: p(x).crop((0, (oh - ow * h / w) / 2, ow, (oh + ow * h / w) / 2)),
            process)
    w = min(w, ow)
    h = min(h, oh)

    # Resize to target sizes
    imgdown = partial(
        lambda p, x: p(x).resize((w, h), Image.LANCZOS),
        process)
    img2down = partial(
        lambda p, x: p(x).resize((w * 2, h * 2), Image.LANCZOS),
        process)
    outpathbase = os.path.splitext(repo_path)[0]
    outpath = output_path + outpathbase
    os.makedirs(os.path.dirname(outpath), exist_ok=True)
    if repo_path.endswith(".jpg"):
        imgdown(img).save(outpath + ".jpg", progressive=True, optimize=True)
        img2down(img).save(outpath + "@2x.jpg", progressive=True, optimize=True)
        imgdown(img).save(outpath + ".webp")
        img2down(img).save(outpath + "@2x.webp")
        yield outpathbase + ".jpg"
        yield outpathbase + ".webp"
        yield outpathbase + "@2x.jpg"
        yield outpathbase + "@2x.webp"
    elif repo_path.endswith(".png"):
        imgdown(img).save(outpath + ".png")
        img2down(img).save(outpath + "@2x.png")
        imgdown(img).save(outpath + ".webp")
        img2down(img).save(outpath + "@2x.webp")
        yield outpathbase + ".png"
        yield outpathbase + ".webp"
        yield outpathbase + "@2x.png"
        yield outpathbase + "@2x.webp"
    elif repo_path.endswith(".webp") or repo_path.endswith(".gif"):
        webpopt = dict(exact=True, method=6, quality=80)
        gifopt = dict(optimize=True)
        frames = ImageSequence.all_frames(img, lambda im: imgdown(im))
        frames[0].save(outpath + ".webp", save_all=True, append_images=frames[1:], **webpopt)
        frames[0].save(outpath + ".gif", save_all=True, append_images=frames[1:], **gifopt)
        frames2down = ImageSequence.all_frames(img, lambda im: img2down(im))
        frames2down[0].save(outpath + "@2x.webp", save_all=True, append_images=frames2down[1:], **webpopt)
        frames2down[0].save(outpath + "@2x.gif", save_all=True, append_images=frames2down[1:], **gifopt)
        yield outpathbase + ".gif"
        yield outpathbase + ".webp"
        yield outpathbase + "@2x.gif"
        yield outpathbase + "@2x.webp"
    else:
        raise RuntimeError(f"Unsupported file type {repo_path}")


def _copy_file(input_path, output_path, repo_path, strip_prefix=None, **kwargs):
    del kwargs
    outrepopath = repo_path
    if strip_prefix is not None and outrepopath.startswith(strip_prefix):
        outrepopath = outrepopath[len(strip_prefix):]
    os.makedirs(os.path.dirname(output_path + outrepopath), exist_ok=True)
    with open(input_path + repo_path, "rb") as f, \
         open(output_path + outrepopath, "wb") as f2:
        f2.write(f.read())
        f2.flush()
        yield outrepopath


def _prepare_data():
    raw_data = {}
    raw_data["citeCounts"] = _get_cite_counts()
    return raw_data


def _cssmin(input_path, output_path, repo_path, minify_css=True, **kwargs):
    del kwargs

    os.makedirs(os.path.dirname(output_path + repo_path), exist_ok=True)
    with open(input_path + repo_path, "r", encoding="utf8") as f, \
         open(output_path + repo_path, "w", encoding="utf8") as f2:
        css = f.read()
        if minify_css:
            from rcssmin import cssmin  # type: ignore
            css = cssmin(css)
        f2.write(css)
        f2.flush()
        yield repo_path


def _jsmin(input_path, output_path, repo_path, minify_js=True, **kwargs):
    del kwargs

    os.makedirs(os.path.dirname(output_path + repo_path), exist_ok=True)
    with open(input_path + repo_path, "r", encoding="utf8") as f, \
         open(output_path + repo_path, "w", encoding="utf8") as f2:
        js = f.read()
        if minify_js:
            from rjsmin import jsmin  # type: ignore
            js = jsmin(js)
        f2.write(js)
        f2.flush()
        yield repo_path


def _html_redirect(input_path, output_path, repo_path, *, target, **kwargs):
    del kwargs, input_path

    os.makedirs(os.path.dirname(output_path + repo_path), exist_ok=True)
    with open(output_path + repo_path, "w", encoding="utf8") as f:
        f.write(f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta http-equiv="refresh" content="0;url={target}">
  <title>Redirecting...</title>
</head>
<body>
  <h1>Redirecting...</h1>
  <p>This page has been moved to <a href="{target}">{target}</a>.</p>
</body>
</html>
""")
    yield repo_path


TRANSFORMS = {
    "/images/profile.png": partial(_resize_image, size=(240, 240)),
    "/images/project-*": partial(_resize_image, size=(86, 86)),
    "/images/pd-*": partial(_resize_image, size=(86, 86)),
    "/assets/*": partial(_copy_file),
    "/scripts.js": partial(_jsmin),
    "/*.css": partial(_cssmin),
    "/robots.txt": partial(_copy_file),
    "/*.pdf": partial(_copy_file),
    "/index.html": partial(_transform_template, data=_prepare_data),
    "+/rg.html": partial(_html_redirect, target="https://jkulhanek.com/reading-group"),
    "+/isr-reading-group.html": partial(_html_redirect, target="https://jkulhanek.com/reading-group"),
    "+/nerfbaselines/index.html": partial(_html_redirect, target="https://nerfbaselines.github.io/"),
    "+/nerfbaselines/video.html": partial(_html_redirect, target="https://nerfbaselines.github.io/video.html"),
    "/[!_]*.html": partial(_transform_template),
}


def _formatsize(size):
    if size > 1024 * 1024:
        return f"{size / 1024 / 1024:.2f} MB"
    elif size > 1024:
        return f"{size / 1024:.2f} KB"
    else:
        return f"{size} B"


def _transform(input_path, output, files=None, **kwargs):
    if files is None:
        files = []
        for root, _, fs in os.walk(input_path):
            for file in fs:
                files.append(os.path.join(root, file))
    for file in files:
        repopath = "/" + os.path.relpath(file, input_path)
        if repopath.startswith("/dist"):
            continue
        oldsize = os.path.getsize(file)
        for k, func in TRANSFORMS.items():
            if k.startswith("+"):
                continue
            if fnmatch.fnmatch(repopath, k):
                print(f"  {repopath}:")
                for outname in func(input_path, output, repopath, **kwargs):
                    size = os.path.getsize(output + outname)
                    print(f"    {outname} (\033[93;1m{_formatsize(oldsize)}\033[0m -> \033[92;1m{_formatsize(size)}\033[0m)")
                break
    if any(k.startswith("+") for k in TRANSFORMS):
        print()
        print(f"  Added:")
    # Generate added files
    for k, func in TRANSFORMS.items():
        if not k.startswith("+"):
            continue
        repopath = k[1:]
        for outname in func(input_path, output, repopath, **kwargs):
            size = os.path.getsize(output + outname)
            print(f"    {outname} (\033[92;1m{_formatsize(size)}\033[0m)")


def build(input_path, output, **kwargs):
    if os.path.exists(output):
        raise FileExistsError(f"Output directory {output} already exists.")

    # Transform files
    logging.info("Transforming files")
    _transform(input_path, output, **kwargs)


def start_dev_server(**kwargs):
    from livereload import Server

    with tempfile.TemporaryDirectory() as output:
        input_path = os.path.dirname(os.path.abspath(__file__))

        # Build first version
        os.rmdir(output)
        build(input_path, output, **kwargs)

        # Create server and watch for changes
        server = Server()
        SFH = server.SFH
        class HtmlRewriteSFHserver(SFH):
            def get(self, path, *args, **kwargs):
                fname = path.split("/")[-1]
                if fname and "." not in fname:
                    path = f"{path}.html"
                return super().get(path, *args, **kwargs)
        server.SFH = HtmlRewriteSFHserver
        logging.getLogger("tornado").setLevel(logging.WARNING)
        server.watch(input_path + "/**/*", partial(
            _transform, input_path, output, **kwargs))
        server._setup_logging = lambda: None
        logging.info("Starting dev server")
        server.serve(root=output)


def get_click_group():
    main = click.Group("web")

    @main.command("dev")
    @click.option("--minify-html/--no-minify-html", default=False, help="Minify HTML output.")
    @click.option("--minify-css/--no-minify-css", default=False, help="Minify CSS output.")
    @click.option("--minify-js/--no-minify-js", default=False, help="Minify JS output.")
    def _(**kwargs):
        _setup_logging(False)
        start_dev_server(**kwargs)

    @main.command("build")
    @click.option("--output", required=True, help="Output directory.")
    @click.option("--base-path", default="", help="Base path for the website.")
    @click.option("--minify-html/--no-minify-html", default=True, help="Minify HTML output.")
    @click.option("--minify-css/--no-minify-css", default=True, help="Minify CSS output.")
    @click.option("--minify-js/--no-minify-js", default=True, help="Minify JS output.")
    def _(output, base_path, **kwargs):
        _setup_logging(False)
        input_path = os.path.dirname(os.path.abspath(__file__))
        build(input_path, output, base_path=base_path, **kwargs)

    return main


if __name__ == "__main__":
    get_click_group()() 
