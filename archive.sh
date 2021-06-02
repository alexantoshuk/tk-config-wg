#!/bin/bash

DATA=$(date +'%d.%m.%Y')
git archive -o ../config_${DATA}.zip HEAD
