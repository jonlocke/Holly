set -x
mypid=`docker inspect --format '{{.State.Pid}}' holly-test`
sudo kill -9 $mypid; wait 2; sudo docker stop holly-test; wait 2; sudo docker rm -f holly-test 
./build-docker.sh
./docker-run-test.sh


