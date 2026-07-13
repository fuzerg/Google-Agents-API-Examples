title: Debug Pods
source: https://kubernetes.io/docs/tasks/debug/debug-application/debug-pods/
---
This guide helps you debug applications deployed into Kubernetes that are not
behaving correctly. It is *not* a guide for debugging your cluster.

## Diagnosing the problem

The first step in troubleshooting is triage. What is the problem? Start by
looking at the current state of the Pod and its recent events:

```shell
kubectl describe pods ${POD_NAME}
```

Look at the state of the containers in the Pod. Are they all `Running`? Have
there been recent restarts? Continue debugging depending on the state of the
Pod.

## My pod stays pending

If a Pod is stuck in `Pending` it cannot be scheduled onto a node. Generally
this is because there are insufficient resources of one type or another. Look at
the output of `kubectl describe ...` above — there should be messages from the
scheduler about why it cannot schedule your Pod. Reasons include:

- **You don't have enough resources.** You may have exhausted the supply of CPU
  or memory in your cluster. You need to delete Pods, adjust resource requests,
  or add new nodes to your cluster.
- **You are using `hostPort`.** Binding a Pod to a `hostPort` limits the number
  of places the Pod can be scheduled. In most cases `hostPort` is unnecessary —
  try using a Service object to expose your Pod instead.

## My pod stays waiting

If a Pod is stuck in the `Waiting` state, it has been scheduled to a worker node
but cannot run on that machine. Again, the information from `kubectl describe ...`
should be informative. The most common cause of `Waiting` Pods is a failure to
pull the image. Check three things:

- Make sure the name of the image is correct.
- Have you pushed the image to the registry?
- Try to manually pull the image to see if it can be pulled. For example, if you
  use Docker on your workstation, run `docker pull <image>`.

## My pod stays terminating

If a Pod is stuck in the `Terminating` state, a deletion has been issued but the
control plane is unable to delete the Pod object. This typically happens if the
Pod has a **finalizer** and an admission webhook in the cluster prevents the
control plane from removing the finalizer. Check whether your cluster has any
`ValidatingWebhookConfiguration` or `MutatingWebhookConfiguration` that target
`UPDATE` operations for `pods` resources.

## My pod is crashing or otherwise unhealthy

Once your Pod has been scheduled, the methods described in **Debug Running Pods**
are available for debugging — in particular, inspect the container's logs
(including the previous instance's logs with `kubectl logs --previous`) and the
container's `Last State`, `Reason`, and `Exit Code` from `kubectl describe pod`.

## My pod is running but not doing what I told it to do

If your Pod is not behaving as expected, there may be an error in your Pod
description that was silently ignored when the Pod was created. Often a section
of the Pod description is nested incorrectly, or a key name is typed incorrectly.
For example, if you misspelled `command` as `commnd`, the Pod would be created
but would not use the command line you intended.

Delete your Pod and try creating it again with the `--validate` option:

```shell
kubectl apply --validate -f mypod.yaml
```

You can also confirm the Pod on the API server matches the Pod you meant to
create:

```shell
kubectl get pods/mypod -o yaml > mypod-on-apiserver.yaml
```

Then compare the original description with the one returned from the API server.
Lines present in your original that are missing from the API server version may
indicate a problem with your Pod spec.
