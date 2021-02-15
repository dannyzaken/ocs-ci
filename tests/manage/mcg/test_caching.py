import logging
import pytest
from ocs_ci.framework.testlib import (
    MCGTest,
    tier1,
    # tier2,
    # tier3,
    # tier4,
    # tier4a,
)
from ocs_ci.ocs.bucket_utils import sync_object_directory, verify_s3_object_integrity
from ocs_ci.framework.pytest_customization.marks import skipif_aws_creds_are_missing
from ocs_ci.ocs import constants

# from ocs_ci.ocs.cluster import CephCluster
# from ocs_ci.ocs.exceptions import CommandFailed
# from ocs_ci.ocs.resources import pod

logger = logging.getLogger(__name__)


@skipif_aws_creds_are_missing
class TestNamespace(MCGTest):
    """
    Test creation of a namespace resource
    """

    MCG_NS_RESULT_DIR = "/result"
    MCG_NS_ORIGINAL_DIR = "/original"
    # TODO: fix this when https://github.com/red-hat-storage/ocs-ci/issues/3338
    # is resolved
    DEFAULT_REGION = "us-east-2"

    @tier1
    @pytest.mark.parametrize(
        argnames=["platform"],
        argvalues=[
            pytest.param(constants.AWS_PLATFORM),
        ],
    )
    def test_namespace_cache_bucket_creation(
        self, ns_resource_factory, bucket_factory, platform
    ):
        """
        Test namespace bucket creation using the MCG RPC.
        """
        # Create the namespace resource and verify health
        ns_resource_name = ns_resource_factory(platform=platform)[1]

        # Create the namespace bucket on top of the namespace resource
        bucket_factory(
            amount=1, interface="mcg-cache", hub_resource=ns_resource_name, ttl_ms=60000
        )

    @tier1
    @pytest.mark.parametrize(
        argnames=["platform"],
        argvalues=[
            pytest.param(constants.AWS_PLATFORM),
        ],
    )
    def test_namespace_cache_read_object_copies_to_cache(
        self,
        mcg_obj,
        cld_mgr,
        awscli_pod,
        ns_resource_factory,
        bucket_factory,
        platform,
    ):
        """
        Test namespace bucket creation using the MCG RPC.
        """
        # Create the namespace resource and verify health
        result = ns_resource_factory(platform=platform)
        target_bucket_name = result[0]
        ns_resource_name = result[1]

        # Create the namespace bucket on top of the namespace resource
        cache_bucket_name = bucket_factory(
            amount=1, interface="mcg-cache", hub_resource=ns_resource_name, ttl_ms=60000
        )[0].name

        s3_creds = {
            "access_key_id": cld_mgr.aws_client.access_key,
            "access_key": cld_mgr.aws_client.secret_key,
            "endpoint": constants.MCG_NS_AWS_ENDPOINT,
            "region": self.DEFAULT_REGION,
        }
        # Upload a file directly to AWS
        uploaded_obj = self.write_files_to_pod_and_upload(
            mcg_obj,
            awscli_pod,
            bucket_to_write=target_bucket_name,
            amount=1,
            s3_creds=s3_creds,
        )[0]
        # Read file from ns bucket
        self.download_files(mcg_obj, awscli_pod, bucket_to_read=cache_bucket_name)

        # verify that the file md exists, meaning the file is in cache
        list_objects_res = mcg_obj.send_rpc_query(
            "object_api",
            "list_objects",
            {
                "bucket": cache_bucket_name,
            },
        )

        # list objects rpc on the cache bucket will list only objects which are in the cache
        # check that the uploaded object is in the list
        cached_objects_keys = [
            obj.get("key")
            for i, obj in enumerate(list_objects_res.json().get("reply").get("objects"))
        ]
        assert uploaded_obj in cached_objects_keys

    @tier1
    @pytest.mark.parametrize(
        argnames=["platform"],
        argvalues=[
            pytest.param(constants.AWS_PLATFORM),
        ],
    )
    def test_namespace_cache_read_object_from_cache(
        self,
        mcg_obj,
        cld_mgr,
        awscli_pod,
        ns_resource_factory,
        bucket_factory,
        platform,
    ):
        """
        Test namespace bucket creation using the MCG RPC.
        """
        # Create the namespace resource and verify health
        result = ns_resource_factory(platform=platform)
        target_bucket_name = result[0]
        ns_resource_name = result[1]

        # Create the namespace bucket on top of the namespace resource
        cache_bucket_name = bucket_factory(
            amount=1, interface="mcg-cache", hub_resource=ns_resource_name, ttl_ms=60000
        )[0].name

        s3_creds = {
            "access_key_id": cld_mgr.aws_client.access_key,
            "access_key": cld_mgr.aws_client.secret_key,
            "endpoint": constants.MCG_NS_AWS_ENDPOINT,
            "region": self.DEFAULT_REGION,
        }
        # Upload a file directly to AWS
        self.write_files_to_pod_and_upload(
            mcg_obj,
            awscli_pod,
            bucket_to_write=target_bucket_name,
            amount=1,
            s3_creds=s3_creds,
        )[0]
        # Read file from ns bucket this should copy to cache
        self.download_files(mcg_obj, awscli_pod, bucket_to_read=cache_bucket_name)

        # # verify that the file md exists, meaning the file is in cache
        # list_objects_res = mcg_obj.send_rpc_query(
        #     "object_api",
        #     "list_objects",
        #     {
        #         "bucket": cache_bucket_name,
        #     },
        # )

        # overwrite the file in AWS. this should not modify the object in cache
        self.write_files_to_pod_and_upload(
            mcg_obj,
            awscli_pod,
            bucket_to_write=target_bucket_name,
            amount=1,
            s3_creds=s3_creds,
        )[0]

        # read object from cache **before** the TTL pass. this should return the data from first write
        # and not the second overwrite in AWS

    def write_files_to_pod_and_upload(
        self, mcg_obj, awscli_pod, bucket_to_write, amount=1, s3_creds=None
    ):
        """
        Upload files to bucket (NS or uls)
        """
        awscli_pod.exec_cmd_on_pod(command=f"mkdir -p {self.MCG_NS_ORIGINAL_DIR}")
        full_object_path = f"s3://{bucket_to_write}"

        objects_list = []

        for i in range(amount):
            file_name = f"testfile{i}.txt"
            awscli_pod.exec_cmd_on_pod(
                f"dd if=/dev/urandom of={self.MCG_NS_ORIGINAL_DIR}/{file_name} bs=1M count=1 status=none"
            )
            objects_list.append(file_name)
        if s3_creds:
            # Write data directly to target bucket from original dir
            sync_object_directory(
                awscli_pod,
                self.MCG_NS_ORIGINAL_DIR,
                full_object_path,
                signed_request_creds=s3_creds,
            )
        else:
            # Write data directly to NS bucket from original dir
            sync_object_directory(
                awscli_pod, self.MCG_NS_ORIGINAL_DIR, full_object_path, mcg_obj
            )

        return objects_list

    def download_files(self, mcg_obj, awscli_pod, bucket_to_read, s3_creds=None):
        """
        Download files from bucket (NS or uls)
        """
        awscli_pod.exec_cmd_on_pod(command=f"mkdir {self.MCG_NS_RESULT_DIR}")
        ns_bucket_path = f"s3://{bucket_to_read}"

        if s3_creds:
            # Read data directly from target bucket (uls) to result dir
            sync_object_directory(
                awscli_pod,
                ns_bucket_path,
                self.MCG_NS_RESULT_DIR,
                signed_request_creds=s3_creds,
            )
        else:
            # Read data from NS bucket to result dir
            sync_object_directory(
                awscli_pod, ns_bucket_path, self.MCG_NS_RESULT_DIR, mcg_obj
            )

    def compare_dirs(self, awscli_pod, amount=1):
        # Checksum is compared between original and result object
        result = True
        for i in range(amount):
            file_name = f"testfile{i}.txt"
            original_object_path = f"{self.MCG_NS_ORIGINAL_DIR}/{file_name}"
            result_object_path = f"{self.MCG_NS_RESULT_DIR}/{file_name}"
            if not verify_s3_object_integrity(
                original_object_path=original_object_path,
                result_object_path=result_object_path,
                awscli_pod=awscli_pod,
            ):
                logger.warning(
                    f"Checksum comparision between original object "
                    f"{original_object_path} and result object "
                    f"{result_object_path} failed"
                )
                result = False
        return result
