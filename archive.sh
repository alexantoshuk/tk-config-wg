#!/bin/bash

NAME=$(basename $PWD)
DATA=$(date +'%d.%m.%Y-%H.%M')
git archive -o ../${NAME}-${DATA}.zip HEAD
