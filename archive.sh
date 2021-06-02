#!/bin/bash

NAME=$(basename $PWD)
DATA=$(date +'%d.%m.%Y')
git archive -o ../${NAME}-${DATA}.zip HEAD
