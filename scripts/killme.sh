mmypid=`docker inspect --format '{{.State.Pid}}' $1`
sudo kill -9 $mmypid && sleep 15 && docker stop $1; docker rm $1

