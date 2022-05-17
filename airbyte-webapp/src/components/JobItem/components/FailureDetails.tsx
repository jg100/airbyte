import { useIntl } from "react-intl";
import styled from "styled-components";

import { Attempt, Failure } from "core/domain/job/Job";

type IProps = {
  attempts?: Attempt[];
};

const ExpandedFailureContainer = styled.div`
  font-size: 12px;
  line-height: 15px;
  padding: 10px;
  padding-left: 40px;
  color: ${({ theme }) => theme.greyColor40};
`;

const getFailureFromAttempt = (attempt: Attempt) => {
  return attempt.failureSummary?.failures[0];
};

const ErrorDetails: React.FC<IProps> = ({ attempts }) => {
  const { formatMessage } = useIntl();

  if (!attempts || attempts.length === 0) {
    return null;
  }

  const getInternalFailureMessage = (failure: Failure) => {
    const failureMessage = failure?.internalMessage ?? formatMessage({ id: "errorView.unknown" });
    return `${formatMessage({
      id: "sources.additionalFailureInfo",
    })}: ${failureMessage}`;
  };

  const attempt = attempts[attempts.length - 1];
  const failure = getFailureFromAttempt(attempt);

  if (!failure) {
    return null;
  }

  const internalMessage = getInternalFailureMessage(failure);
  return <ExpandedFailureContainer>{internalMessage}</ExpandedFailureContainer>;
};

export default ErrorDetails;
