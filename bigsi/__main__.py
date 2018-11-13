#! /usr/bin/env python
from __future__ import print_function
import sys
import os
import argparse
import redis
import json
import math

sys.path.append(os.path.realpath(os.path.join(os.path.dirname(__file__), "..")))
from bigsi.version import __version__
import logging

logging.basicConfig(level=logging.DEBUG)

logger = logging.getLogger(__name__)
from bigsi.utils import DEFAULT_LOGGING_LEVEL

logger.setLevel(DEFAULT_LOGGING_LEVEL)


import hug
import tempfile
from bigsi.graph import BIGSI

BFSIZE = int(os.environ.get("BFSIZE", 25000000))
NUM_HASHES = int(os.environ.get("NUM_HASHES", 3))

from bigsi.cmds.insert import insert
from bigsi.cmds.search import search


from bigsi.cmds.samples import samples


from bigsi.cmds.delete import delete
from bigsi.cmds.bloom import bloom
from bigsi.cmds.build import build
from bigsi.cmds.merge import merge


from bigsi.utils.cortex import GraphReader
from bigsi.utils import seq_to_kmers
import cProfile
from bigsi.version import __version__
import humanfriendly


def do_cprofile(func):
    def profiled_func(*args, **kwargs):
        profile = cProfile.Profile()
        try:
            profile.enable()
            result = func(*args, **kwargs)
            profile.disable()
            return result
        finally:
            profile.print_stats()

    return profiled_func


API = hug.API("bigsi-%s" % str(__version__))
STORAGE = os.environ.get("STORAGE", "berkeleydb")
BDB_DB_FILENAME = os.environ.get("BDB_DB_FILENAME", "./db")
CACHESIZE = int(os.environ.get("CACHESIZE", 1))
# DEFAULT_GRAPH = GRAPH = Graph(BDB_DB_FILENAME)


DEFUALT_DB_DIRECTORY = "./db-bigsi/"


def extract_kmers_from_ctx(ctx, k):
    gr = GraphReader(ctx)
    for i in gr:
        for kmer in seq_to_kmers(i.kmer.canonical_value, k):
            yield kmer


def bf_range_calc(index, i, N):
    batch_size = math.ceil(index.bloom_filter_size / N)
    i = list(range(0, index.bloom_filter_size, batch_size))[i - 1]
    j = i + batch_size
    return (i, j)


@hug.object(name="bigsi", version="0.1.1", api=API)
@hug.object.urls("/", requires=())
class bigsi(object):
    @hug.object.cli
    @hug.object.post("/init", output_format=hug.output_format.json)
    def init(self, db, k=31, m=25 * 10 ** 6, h=3, force: hug.types.smart_boolean = False):
        bigsi = BIGSI.create(db=db, k=k, m=m, h=h, force=force)
        return {"k": k, "m": m, "h": h, "db": db}

    @hug.object.cli
    @hug.object.post("/insert", output_format=hug.output_format.json)
    def insert(self, db: hug.types.text, bloomfilter, sample, i: int = 1, N: int = 1):
        """Inserts a bloom filter into the graph

        e.g. bigsi insert ERR1010211.bloom ERR1010211

        """
        index = BIGSI(db)
        bf_range = bf_range_calc(index, i, N)

        return insert(graph=index, bloomfilter=bloomfilter, sample=sample, bf_range=bf_range)

    @hug.object.cli
    @hug.object.post("/bloom")
    def bloom(self, outfile, db=DEFUALT_DB_DIRECTORY, kmers=None, seqfile=None, ctx=None, N: int = 1):
        index = BIGSI(db, mode="r")
        """Creates a bloom filter from a sequence file or cortex graph. (fastq,fasta,bam,ctx)

        e.g. index insert ERR1010211.ctx

        """
        if ctx:
            kmers = extract_kmers_from_ctx(ctx, index.kmer_size)
        if not kmers and not seqfile:
            return "--kmers or --seqfile must be provided"
        batch_size = math.ceil(index.bloom_filter_size / N)
        bf_range = range(0, index.bloom_filter_size, batch_size)

        bf = bloom(
            outfile=outfile, kmers=kmers, kmer_file=seqfile, graph=index, bf_range=bf_range, batch_size=batch_size
        )

    @hug.object.cli
    @hug.object.post("/build", output_format=hug.output_format.json)
    def build(
        self,
        db: hug.types.text,
        bloomfilters: hug.types.multiple,
        samples: hug.types.multiple = [],
        max_memory: hug.types.text = "",
        lowmem: hug.types.smart_boolean = False,
        i: int = 1,
        N: int = 1,
    ):
        index = BIGSI(db)
        if samples:
            assert len(samples) == len(bloomfilters)
        else:
            samples = bloomfilters
        if max_memory:
            max_memory_bytes = humanfriendly.parse_size(max_memory)
        else:
            max_memory_bytes = None
        if i < 1:
            raise ValueError("Batch index is one-based. Use 1 for first batch, not 0.")
        bf_range = bf_range_calc(index, i, N)
        print(bf_range)

        return build(
            index=index,
            bloomfilter_filepaths=bloomfilters,
            samples=samples,
            max_memory=max_memory_bytes,
            lowmem=lowmem,
            bf_range=bf_range,
        )

    @hug.object.cli
    @hug.object.post("/merge", output_format=hug.output_format.json)
    def merge(self, db1: hug.types.text, db2: hug.types.text):
        BIGSI(db1).merge(BIGSI(db2))
        return {"result": "merged %s into %s." % (db2, db1)}

    @hug.object.cli
    @hug.object.get(
        "/search",
        examples="seq=ACACAAACCATGGCCGGACGCAGCTTTCTGA",
        output_format=hug.output_format.json,
        response_headers={"Access-Control-Allow-Origin": "*"},
    )
    # @do_cprofile
    def search(
        self,
        db: hug.types.text = None,
        seq: hug.types.text = None,
        seqfile: hug.types.text = None,
        threshold: hug.types.float_number = 1.0,
        output_format: hug.types.one_of(("json", "tsv", "fasta")) = "json",
        pipe_out: hug.types.smart_boolean = False,
        pipe_in: hug.types.smart_boolean = False,
        cachesize: hug.types.number = 4,
        score: hug.types.smart_boolean = False,
        nproc: hug.types.number = 4,
    ):
        if db is None:
            db = BDB_DB_FILENAME
        bigsi = BIGSI(db, cachesize=cachesize, nproc=nproc, mode="r")
        """Returns samples that contain the searched sequence.
        Use -f to search for sequence from fasta"""
        if output_format in ["tsv", "fasta"]:
            pipe_out = True

        if not pipe_in and (not seq and not seqfile):
            return "-s or -f must be provided"
        if seq == "-" or pipe_in:
            _, fp = tempfile.mkstemp(text=True)
            with open(fp, "w") as openfile:
                for line in sys.stdin:
                    openfile.write(line)
            result = search(
                seq=None,
                fasta_file=fp,
                threshold=threshold,
                graph=bigsi,
                output_format=output_format,
                pipe=pipe_out,
                score=score,
            )

        else:
            result = search(
                seq=seq,
                fasta_file=seqfile,
                threshold=threshold,
                graph=bigsi,
                output_format=output_format,
                pipe=pipe_out,
                score=score,
            )

        if not pipe_out:
            return result

    @hug.object.cli
    @hug.object.delete("/", output_format=hug.output_format.json)
    def delete(self, db: hug.types.text = None):
        try:
            bigsi = BIGSI(db)
        except ValueError:
            pass
        else:
            return delete(bigsi)

    # @hug.object.cli
    # @hug.object.get('/graph', output_format=hug.output_format.json)
    # def stats(self):
    #     return stats(graph=get_graph())

    @hug.object.cli
    @hug.object.get("/samples", output_format=hug.output_format.json)
    def samples(
        self, sample_name: hug.types.text = None, db: hug.types.text = None, delete: hug.types.smart_boolean = False
    ):
        return samples(sample_name, graph=get_graph(bdb_db_filename=db), delete=delete)

    # @hug.object.cli
    # @hug.object.post('/dump', output_format=hug.output_format.json)
    # def dump(self, filepath):
    #     r = dump(graph=get_graph(), file=filepath)
    #     return r

    # @hug.object.cli
    # @hug.object.post('/load', output_format=hug.output_format.json)
    # def load(self, filepath):
    #     r = load(graph=get_graph(), file=filepath)
    #     return r


def main():
    API.cli()


if __name__ == "__main__":
    main()
