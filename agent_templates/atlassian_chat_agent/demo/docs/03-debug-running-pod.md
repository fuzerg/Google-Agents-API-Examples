title: Debug Running Pods
source: https://kubernetes.io/docs/tasks/debug/debug-application/debug-running-pod/
---
This page explains how to debug Pods running (or crashing) on a node.

## Using kubectl describe pod to fetch details

`kubectl describe pod` retrieves a lot of information about a Pod and its
containers:

```shell
kubectl describe pod ${POD_NAME}
```

The output shows configuration (labels, resource requirements) and status
(container state, readiness, restart count, and a log of recent events). Key
fields to read:

- **State** — one of `Waiting`, `Running`, or `Terminated`. For a terminated or
  restarting container, look at `Last State`, `Reason`, and `Exit Code`.
- **Restart Count** — how many times the container has restarted. A high and
  climbing count is a strong signal of a crash loop (`CrashLoopBackOff`) for
  containers with a restart policy of `Always`.
- **Events** — recent events for the Pod. `Reason` and `Message` tell you what
  happened (for example, image pull errors or scheduling failures).

## Example: debugging pending pods

A common scenario detectable via events is a Pod that won't fit on any node
because it requests more resources than are free. Run `kubectl describe pod` on
the pending Pod and look at its events; the scheduler reports `FailedScheduling`
with a message such as "Node didn't have enough resource: CPU". To correct this,
reduce the Pod's resource requests, scale down replicas, or add nodes.

You can also list events across the namespace:

```shell
kubectl get events --namespace=my-namespace
```

## Examining pod logs

First, look at the logs of the affected container:

```shell
kubectl logs ${POD_NAME} -c ${CONTAINER_NAME}
```

If your container has previously crashed, you can access the **previous**
container's crash log — this is often the key to diagnosing a `CrashLoopBackOff`:

```shell
kubectl logs ${POD_NAME} -c ${CONTAINER_NAME} --previous
```

## Debugging with container exec

If the container image includes debugging utilities, you can run commands inside
a specific container:

```shell
kubectl exec ${POD_NAME} -c ${CONTAINER_NAME} -- ${CMD} ${ARG1} ${ARG2}
```

You can open an interactive shell with the `-i` and `-t` flags:

```shell
kubectl exec -it ${POD_NAME} -- sh
```

## Debugging with an ephemeral debug container

Ephemeral containers are useful for interactive troubleshooting when
`kubectl exec` is insufficient — because the container has crashed, or the
container image doesn't include debugging utilities (for example, distroless
images). Use `kubectl debug` to add an ephemeral container to a running Pod:

```shell
kubectl debug -it ${POD_NAME} --image=busybox:1.28 --target=${CONTAINER_NAME}
```

The `--target` parameter targets the process namespace of another container (it
must be supported by the container runtime).

## Debugging using a copy of the pod

Sometimes Pod configuration makes troubleshooting difficult — for example, your
application crashes on startup, or the image has no shell. In those cases,
`kubectl debug` can create a **copy** of the Pod with changed configuration.

To debug a crashing application, copy the Pod but change its command to an
interactive shell so you can run the container command manually and inspect the
filesystem:

```shell
kubectl debug ${POD_NAME} -it --copy-to=myapp-debug --container=${CONTAINER_NAME} -- sh
```

A container caught in a crash loop typically shows up like this under
`kubectl describe pod`:

```none
State:          Waiting
  Reason:       CrashLoopBackOff
Last State:     Terminated
  Reason:       Error
  Exit Code:    1
```

Remember to clean up any debugging Pods when you are finished:

```shell
kubectl delete pod myapp myapp-debug
```
