FROM python:3.4.3
RUN mkdir -p /usr/src/app
WORKDIR /usr/src/app
RUN pip install --upgrade pip
ENV BERKELEY_VERSION 4.8.30

# Download, configure and install BerkeleyDB
#RUN wget -P /tmp http://download.oracle.com/berkeley-db/db-"${BERKELEY_VERSION}".tar.gz && \
#    tar -xf /tmp/db-"${BERKELEY_VERSION}".tar.gz -C /tmp && \
#    rm -f /tmp/db-"${BERKELEY_VERSION}".tar.gz
#RUN cd /tmp/db-"${BERKELEY_VERSION}"/build_unix && \
#    ../dist/configure && make && make install

# Upgrade your gcc to version at least 4.7 to get C++11 support.
#RUN apt-get install -y build-essential checkinstall

# Install gflags snappy zlib bzip2
#RUN apt-get install -y libgflags-dev libsnappy-dev zlib1g-dev libbz2-dev

# Clone rocksdb
# RUN cd /tmp && git clone https://github.com/facebook/rocksdb.git && cd rocksdb && make clean && make



COPY . /usr/src/app
#COPY requirements.txt /usr/src/app/
RUN BERKELEYDB=/usr/local/Cellar/berkeley-db4/4.8.30/ pip install --no-cache-dir -r requirements.txt
# Install hug
WORKDIR /usr/src/app/hug
RUN python setup.py install

# install atlasseq
WORKDIR /usr/src/app
RUN python setup.py install

CMD atlasseq --help