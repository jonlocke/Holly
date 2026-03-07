mypid=`docker inspect --format '{{.State.Pid}}' $1`
kill -9 $mypid && docker stop $1; docker rm $1

