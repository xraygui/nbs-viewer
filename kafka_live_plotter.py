import nslsii.kafka_utils
from bluesky_kafka import RemoteDispatcher
import matplotlib.pyplot as plt
from tiled.client import from_profile
import uuid
import datetime
import numpy as np
from bluesky_widgets.models.plot_builders import Lines
from bluesky_widgets.utils.streaming import stream_documents_into_runs as stream_docs
from bluesky_widgets._matplotlib_axes import MatplotlibAxes

plt.ion()
plt.rcParams["figure.raise_window"] = False


def label_maker(run, y):
    return f"Scan {run.metadata['start'].get('scan_id', '?')}"


class RunPlotter:
    def __init__(self, autoclose=True, catalog=None):
        self.autoclose = autoclose
        self.catalog = catalog
        self.reset()

    def reset(self):
        if self.autoclose:
            plt.close("all")
        self.xdata = {}
        self.ydata = {}
        self.scanids = []
        self.models = None
        self.streams = None
        self.ax_list = None

    def get_data_keys(self, start):
        plot_hints = start.get("plot_hints", {})
        xdefault = start.get("motors", ["time"])
        xkey = plot_hints.get("x", xdefault)[0]
        ykeys = sorted(plot_hints.get("y", ["ucal_sc"]))
        imkeys = sorted(plot_hints.get("image", []))
        normkey = plot_hints.get("norm", ["ucal_i0up"])[0]
        return xkey, ykeys, imkeys, normkey

    def plot_average(self, doc):
        run = self.catalog[doc["run_start"]]
        scanid = run.start["scan_id"]
        xkey, ykeys, imkeys, normkey = self.get_data_keys(run.start)
        data = run.primary.read()
        if self.ax_list is None:
            self.new_run(run.start)
            for name, d in run.documents():
                self.stream_documents_into_runs(name, d)
        axs = self.ax_list
        if len(axs[0]) == 1:
            return

        repeat_md = run.start["repeat"]
        if repeat_md["index"] == 0:
            self.xdata = {}
            self.ydata = {}
            self.imdata = {}
            self.normdata = []
            self.scanids = []

        self.scanids.append(scanid)
        for ykey in ykeys:
            if ykey not in self.ydata:
                self.ydata[ykey] = [data[ykey].data]
            else:
                self.ydata[ykey].append(data[ykey].data)
        for imkey in imkeys:
            if imkey not in self.imdata:
                self.imdata[imkey] = [data[imkey].data]
            else:
                self.imdata[imkey].append(data[imkey].data)

        if normkey is not None:
            self.normdata.append(data[normkey].data / np.mean(data[normkey].data))
        else:
            self.normdata.append(1)

        self.xdata[scanid] = data[xkey].data

        for ykey, ax_list in zip(ykeys, axs):
            ax = ax_list[1]
            ax.clear()
            ynormlist = [y / norm for y, norm in zip(self.ydata[ykey], self.normdata)]
            ax.plot(
                self.xdata[scanid],
                np.mean(ynormlist, axis=0),
                color="k",
                label=f"{ykey} normalized by {normkey}",
            )

        if len(imkeys) > 0:
            for imkey, ax_list in zip(imkeys, axs[len(ykeys) :]):
                yy = run.start["plot_hints"]["image_y"][imkey]
                ax = ax_list[1]
                ax.clear()
                ax.contourf(
                    self.xdata[scanid], yy, np.mean(self.imdata[imkey], axis=0), 50
                )

        axs[0][1].set_title("Averages")
        ax.set_xlabel(xkey)

    def stream_documents_into_runs(self, name, doc):
        if self.streams is None:
            pass
        else:
            for stream in self.streams:
                stream(name, doc)

    def new_run(self, start):
        xkey, ykeys, imkeys, normkey = self.get_data_keys(start)
        if "repeat" in start:
            repeat_md = start["repeat"]
            max_runs = repeat_md["len"]
            cols = 2
            if repeat_md["index"] != 0:
                if self.models is not None:
                    return
        else:
            max_runs = 1
            cols = 1
        if normkey is not None:
            self.models = [
                Lines(
                    xkey,
                    [f"mean({normkey})*{ykey}/{normkey}"],
                    max_runs=max_runs,
                    label_maker=label_maker,
                )
                for ykey in ykeys
            ]
        else:
            self.models = [
                Lines(xkey, [ykey], max_runs=max_runs, label_maker=label_maker)
                for ykey in ykeys
            ]
        fig, axs = plt.subplots(
            len(ykeys) + len(imkeys), cols, squeeze=False, sharex=True
        )
        self.ax_list = axs
        self.mpl_ax = []
        for model, ax in zip(self.models, axs):
            model.title = ""
            model.axes.x_label = ""
            self.mpl_ax.append(MatplotlibAxes(model.axes, ax[0]))
        model.axes.x_label = xkey
        self.streams = [stream_docs(model.add_run) for model in self.models]

    def new_document(self, name, doc):
        if name == "start":
            print("received start doc!")
            self.new_run(doc)
        if name == "stop":
            print("received stop doc!")
            self.plot_average(doc)
        self.stream_documents_into_runs(name, doc)


def plot_kafka(beamline_acronym):
    c = from_profile("ucal")
    plotter = RunPlotter(autoclose=False, catalog=c)

    kafka_config = nslsii.kafka_utils._read_bluesky_kafka_config_file(
        config_file_path="/etc/bluesky/kafka.yml"
    )

    # this consumer should not be in a group with other consumers
    #   so generate a unique consumer group id for it
    unique_group_id = f"echo-{beamline_acronym}-{str(uuid.uuid4())[:8]}"

    kafka_dispatcher = RemoteDispatcher(
        topics=[f"{beamline_acronym}.bluesky.runengine.documents"],
        bootstrap_servers=",".join(kafka_config["bootstrap_servers"]),
        group_id=unique_group_id,
        consumer_config=kafka_config["runengine_producer_config"],
    )

    kafka_dispatcher.subscribe(plotter.new_document)
    kafka_dispatcher.start(work_during_wait=lambda: plt.pause(0.1))


if __name__ == "__main__":
    plot_kafka("ucal")
